"""Bloque 7a: bandeja de mensajes libres y preguntas del parser como botones.

Reloj: sábado 2026-10-03 15:30 en México ("mañana" = domingo 4 de octubre).
El texto del usuario es siempre FALSO ("llevar tarea"...): nunca debe llegar al log.
"""

import logging
from datetime import timedelta

import pytest

from asistente.bot import handlers
from asistente.bot.conversation import FLOW_TTL
from asistente.core import areas, notes, reminders, tasks
from asistente.timeutil import from_utc_iso, local_to_utc
from tests.botkit import TZ, Bot, module_loop  # noqa: F401


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def all_tasks(conn) -> list[tasks.Task]:
    return [tasks.get_task(conn, row["id"]) for row in conn.execute("SELECT id FROM tasks")]


def pending(conn) -> list[reminders.Reminder]:
    return reminders.list_pending(conn)


def local_hhmm(reminder: reminders.Reminder) -> str:
    from asistente.timeutil import to_local

    local = to_local(from_utc_iso(reminder.fire_at_utc), TZ)
    return f"{local:%Y-%m-%d %H:%M}"


# --- Captura ---------------------------------------------------------------------------------


def test_un_mensaje_libre_se_guarda_primero_como_tarea_sin_area(bot, conn):
    bot.say("comprar leche")
    [task] = all_tasks(conn)
    assert (task.title, task.area_id, task.status, task.source_text) == (
        "comprar leche",
        None,
        "open",
        "comprar leche",
    )
    assert bot.labels() == ["Tarea", "Recordatorio", "Nota", "Cancelar"]


def test_un_extrano_no_recibe_nada_ni_se_guarda_nada(bot, conn):
    bot.say("comprar leche", user=99999)
    bot.press("in:1:k:t", user=99999)
    assert bot.channel.sent_anything is False
    assert all_tasks(conn) == []


def test_un_mensaje_en_blanco_se_ignora(bot, conn):
    bot.say("   ")
    assert all_tasks(conn) == [] and bot.channel.sent_anything is False


# --- Tarea y nota ----------------------------------------------------------------------------


def test_tarea_pregunta_el_area_y_la_asigna(bot, conn):
    bot.say("comprar leche")
    bot.tap("Tarea")
    assert bot.labels() == [
        "universidad",
        "proyectos",
        "iglesia",
        "personal",
        "Sin área",
        "Cancelar",
    ]
    bot.tap("universidad")
    [task] = all_tasks(conn)
    assert task.status == "open"
    assert task.area_id == areas.find_area_by_name(conn, "universidad").id
    assert "Tarea guardada" in bot.last[1]


def test_tarea_sin_area(bot, conn):
    bot.say("comprar leche")
    bot.tap("Tarea")
    bot.tap("Sin área")
    assert all_tasks(conn)[0].area_id is None and all_tasks(conn)[0].status == "open"


def test_si_no_hay_areas_no_se_pregunta(bot, conn):
    for area in areas.list_areas(conn):
        areas.archive_area(conn, area.id)
    bot.say("comprar leche")
    bot.tap("Tarea")
    assert "Tarea guardada" in bot.last[1]


def test_nota_crea_la_nota_y_cierra_la_tarea_como_convertida_no_como_hecha(bot, conn):
    bot.say("la clave del wifi es larga")
    bot.tap("Nota")
    bot.tap("personal")
    [note] = notes.list_notes(conn)
    assert note.text == "la clave del wifi es larga"
    assert note.area_id == areas.find_area_by_name(conn, "personal").id
    task = all_tasks(conn)[0]
    assert (task.status, task.closed_reason) == ("dropped", "converted_to_note")


# --- Recordatorio ----------------------------------------------------------------------------


def test_recordatorio_con_fecha_clara_confirma_con_dia_de_la_semana_y_botones(bot, conn):
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    assert pending(conn) == []  # aún falta el área
    bot.tap("universidad")
    [reminder] = pending(conn)
    assert reminder.text == "llevar tarea" and local_hhmm(reminder) == "2026-10-04 08:00"
    assert reminder.area_id == areas.find_area_by_name(conn, "universidad").id
    text, _ = bot.question
    assert "domingo 4 de octubre, 8:00 am" in text and "llevar tarea" in text
    assert bot.labels() == ["Cambiar", "Deshacer"]
    task = all_tasks(conn)[0]
    assert (task.status, task.closed_reason) == ("dropped", "converted_to_reminder")


def test_hora_por_defecto_se_avisa(bot, conn):
    bot.say("mañana llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert "9:00 am (hora por defecto)" in bot.question[0]
    assert local_hhmm(pending(conn)[0]) == "2026-10-04 09:00"


def test_si_el_titulo_queda_vacio_se_usa_el_texto_original(bot, conn):
    bot.say("mañana 8am")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert pending(conn)[0].text == "mañana 8am"


@pytest.mark.parametrize(
    "text",
    ["Recordar llamar a mamá", "recuérdame llamar a mamá", "recuerdame llamar", "Recuérdenme algo"],
)
def test_un_texto_que_empieza_por_recordar_salta_la_pregunta_de_tipo(bot, conn, text):
    bot.say(text)
    assert "¿En qué área" in bot.question[0]
    bot.tap("Sin área")
    assert "¿Cuándo?" in bot.question[0]  # ya es recordatorio; falta la fecha


def test_recordar_con_fecha_va_directo_a_recordatorio(bot, conn):
    bot.say("recuérdame mañana 8am llevar tarea")
    bot.tap("Sin área")
    assert pending(conn)[0].text == "llevar tarea"


def test_una_palabra_parecida_no_salta_la_pregunta_de_tipo(bot):
    bot.say("recordatorio de la junta")
    assert bot.labels()[0] == "Tarea"


def test_sin_fecha_pregunta_cuando_con_hoy_y_manana(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    text, _ = bot.question
    assert "¿Cuándo?" in text
    assert bot.labels() == ["Hoy 6:00 pm", "Mañana 9:00 am", "Mejor como tarea", "Cancelar"]
    bot.tap("Mañana 9:00 am")
    [reminder] = pending(conn)
    assert reminder.text == "llamar al dentista" and local_hhmm(reminder) == "2026-10-04 09:00"


def test_hoy_18_solo_se_ofrece_si_es_futuro(bot, clock):
    clock.advance(hours=3)  # 18:30 locales
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert bot.labels() == ["Mañana 9:00 am", "Mejor como tarea", "Cancelar"]


def test_hoy_18_pulsado_cuando_ya_paso_no_crea_nada(bot, conn, clock):
    clock.advance(hours=2, minutes=25)  # 17:55 locales: todavía es futuro
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    hoy = bot.choice_id("Hoy 6:00 pm")
    clock.advance(minutes=6)  # 18:01
    bot.press(hoy)
    assert pending(conn) == []
    assert "pasó" in bot.last[1]


def test_responder_la_fecha_con_texto(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    bot.say("mañana 10 am")
    [reminder] = pending(conn)
    assert reminder.text == "llamar al dentista" and local_hhmm(reminder) == "2026-10-04 10:00"


def test_escribir_otra_fecha_pide_el_texto(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    bot.say("mañana por la mañana")  # no se entiende: pregunta, no guarda
    assert pending(conn) == []
    bot.tap("Escribir otra")
    assert "Escribe" in bot.last[1]
    bot.say("mañana 10 am")
    assert local_hhmm(pending(conn)[0]) == "2026-10-04 10:00"


# --- Preguntas del parser --------------------------------------------------------------------


def test_candidato_unico_se_muestra_y_no_se_guarda_hasta_pulsar(bot, conn):
    bot.say("hoy a las 8 llevar tarea")  # a las 15:30 solo queda 8 pm
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert pending(conn) == []
    text, _ = bot.question
    assert "8" in text
    candidate = [label for label in bot.labels() if "8:00 pm" in label]
    assert len(candidate) == 1
    bot.tap("8:00 pm")
    assert local_hhmm(pending(conn)[0]) == "2026-10-03 20:00"


def test_hora_dudosa_ofrece_las_dos_lecturas(bot, conn):
    bot.say("mañana a las 9 llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert pending(conn) == []
    assert "9:00 am" in " ".join(bot.labels()) and "9:00 pm" in " ".join(bot.labels())
    bot.tap("9:00 pm")
    assert local_hhmm(pending(conn)[0]) == "2026-10-04 21:00"


def test_fecha_no_soportada_ofrece_hoy_y_manana(bot, conn):
    bot.say("pagar la renta próximo mes")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert pending(conn) == []
    assert "No entiendo" in bot.question[0]
    assert "Mañana 9:00 am" in bot.labels()


def test_cada_pregunta_lleva_cancelar_y_la_tarea_sigue_en_la_bandeja(bot, conn):
    bot.say("pagar la renta próximo mes")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert bot.labels()[-1] == "Cancelar"
    bot.tap("Cancelar")
    assert pending(conn) == []
    [task] = all_tasks(conn)
    assert (task.status, task.area_id) == ("open", None)
    assert "bandeja" in bot.last[1]


@pytest.mark.parametrize("stage", ["tipo", "area", "serie"])
def test_cancelar_en_cualquier_paso_deja_la_tarea_abierta(bot, conn, stage):
    bot.say("todos los lunes a las 7 pm regar plantas" if stage == "serie" else "regar plantas")
    if stage != "tipo":
        bot.tap("Recordatorio")
    if stage == "serie":
        bot.tap("Sin área")
    bot.tap("Cancelar")
    assert pending(conn) == []
    [task] = all_tasks(conn)
    assert task.status == "open" and task.closed_reason is None
    assert bot.conversation.current(bot.clock) is None


def test_serie_muestra_la_interpretacion_y_no_guarda_hasta_confirmar(bot, conn):
    bot.say("todos los lunes a las 7 pm regar plantas")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert pending(conn) == []
    text, _ = bot.question
    assert "lunes" in text and "lunes 5 de octubre, 7:00 pm" in text
    assert bot.labels() == ["Guardar", "Cancelar"]
    bot.tap("Guardar")
    [reminder] = pending(conn)
    assert reminder.rrule == "FREQ=WEEKLY;BYDAY=MO" and reminder.text == "regar plantas"
    assert bot.labels() == ["Cambiar", "Deshacer"]


def test_el_candidato_se_revisa_al_pulsar_si_ya_paso_no_se_crea(bot, conn, clock):
    clock.advance(hours=4, minutes=25)  # 19:55 locales
    bot.say("hoy a las 8 llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    button = bot.choice_id("8:00 pm")
    clock.advance(minutes=6)  # 20:01
    bot.press(button)
    assert pending(conn) == []
    assert "pasó" in bot.last[1]


# --- Deshacer y Cambiar ----------------------------------------------------------------------


def confirmed(bot) -> reminders.Reminder:
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    return pending(bot.conn)[0]


def test_deshacer_cancela_el_recordatorio_y_devuelve_la_tarea_a_la_bandeja(bot, conn):
    reminder = confirmed(bot)
    bot.tap("Deshacer")
    assert reminders.get_reminder(conn, reminder.id).status == "cancelled"
    [task] = all_tasks(conn)
    assert (task.status, task.closed_reason) == ("open", None)
    assert "bandeja" in bot.last[1]


def test_deshacer_dos_veces_no_da_error(bot, conn):
    confirmed(bot)
    button = bot.choice_id("Deshacer")
    bot.press(button)
    bot.press(button)
    assert "ya no se puede deshacer" in bot.last[1].lower()


def test_deshacer_cuando_ya_sono_dice_que_ya_no_se_puede(bot, conn, clock):
    reminder = confirmed(bot)
    with conn:
        conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder.id,))
    bot.tap("Deshacer")
    assert "ya no se puede deshacer" in bot.last[1].lower()
    assert all_tasks(conn)[0].status == "dropped"


def test_cambiar_deshace_y_pregunta_cuando_de_nuevo(bot, conn):
    old = confirmed(bot)
    bot.tap("Cambiar")
    assert reminders.get_reminder(conn, old.id).status == "cancelled"
    assert "¿Cuándo?" in bot.question[0]
    bot.say("pasado mañana 10 am")
    [new] = pending(conn)
    assert new.id != old.id and new.text == "llevar tarea"
    assert local_hhmm(new) == "2026-10-05 10:00"
    assert all_tasks(conn)[0].closed_reason == "converted_to_reminder"


def test_cambiar_conserva_el_area(bot, conn):
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("iglesia")
    bot.tap("Cambiar")
    bot.tap("Mañana 9:00 am")
    assert pending(conn)[0].area_id == areas.find_area_by_name(conn, "iglesia").id


# --- Estado de la conversación ---------------------------------------------------------------


def test_un_mensaje_nuevo_a_mitad_de_pregunta_descarta_el_flujo_anterior_y_avisa(bot, conn):
    bot.say("comprar leche")
    old_button = bot.choice_id("Tarea")
    bot.say("sacar copias")
    notice = [text for kind, text, _ in bot.channel.log if kind == "text"]
    assert any("sin terminar" in text for text in notice)
    titles = [t.title for t in all_tasks(conn)]
    assert titles == ["comprar leche", "sacar copias"]
    assert all(t.status == "open" and t.area_id is None for t in all_tasks(conn))
    bot.press(old_button)  # botón viejo con un flujo nuevo: no toca nada
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert bot.question[0].startswith(
        "Guardado en tu bandeja"
    )  # la pregunta vigente sigue siendo la nueva
    bot.tap("Nota")
    assert [n.text for n in notes.list_notes(conn)] == []  # aún falta el área


def test_botones_viejos_no_afectan_al_flujo_nuevo(bot, conn):
    bot.say("comprar leche")
    old_kind = bot.choice_id("Tarea")
    bot.say("sacar copias")
    bot.press(old_kind)
    bot.tap("Nota")
    bot.tap("Sin área")
    assert [n.text for n in notes.list_notes(conn)] == ["sacar copias"]
    assert all_tasks(conn)[0].status == "open"


def test_un_texto_que_no_es_fecha_mientras_se_espera_la_fecha_es_captura_nueva(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    bot.say("comprar leche")
    assert pending(conn) == []
    assert [t.title for t in all_tasks(conn)] == ["llamar al dentista", "comprar leche"]
    assert all_tasks(conn)[0].status == "open"  # la primera sigue en la bandeja
    assert bot.labels()[0] == "Tarea"


def test_el_estado_caduca_a_los_10_minutos(bot, conn, clock):
    bot.say("comprar leche")
    button = bot.choice_id("Tarea")
    clock.advance(seconds=FLOW_TTL.total_seconds() + 1)
    bot.press(button)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert all_tasks(conn)[0].status == "open"


def test_una_respuesta_con_fecha_tras_caducar_es_captura_nueva(bot, conn, clock):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    clock.advance(minutes=11)
    bot.say("mañana 10 am")
    assert pending(conn) == []  # no se usó como respuesta
    assert len(all_tasks(conn)) == 2


def test_cada_paso_renueva_la_caducidad(bot, conn, clock):
    bot.say("comprar leche")
    clock.advance(minutes=9)
    bot.tap("Tarea")
    clock.advance(minutes=9)
    bot.tap("personal")
    assert "Tarea guardada" in bot.last[1]


def test_tras_reiniciar_los_botones_viejos_son_inofensivos_y_nada_se_pierde(bot, conn, clock):
    bot.say("comprar leche")
    button = bot.choice_id("Tarea")
    bot.restart()
    clock.advance(seconds=5)
    bot.press(button)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert [(t.title, t.status) for t in all_tasks(conn)] == [("comprar leche", "open")]


def test_tras_reiniciar_la_confirmacion_sigue_pudiendo_deshacerse(bot, conn):
    """Deshacer/Cambiar viven en la base, no en la memoria."""
    reminder = confirmed(bot)
    button = bot.choice_id("Deshacer")
    bot.restart()
    bot.press(button)
    assert reminders.get_reminder(conn, reminder.id).status == "cancelled"


def test_pulsar_dos_veces_el_mismo_boton_no_da_error_ni_duplica(bot, conn):
    bot.say("comprar leche")
    button = bot.choice_id("Nota")
    bot.press(button)
    bot.press(button)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert sum(1 for kind, text, _ in bot.channel.log if "área" in text) == 1


@pytest.mark.parametrize(
    "choice_id",
    ["in", "in:x:k:t", "in:1", "in:1:k", "in:1:zz:1", "in:١٢٣:k:t", "un:1", "un:a:b", "ch:1:2:3"],
)
def test_ids_mal_formados_se_tratan_como_botones_viejos(bot, conn, choice_id):
    bot.say("comprar leche")
    bot.press(choice_id)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert all_tasks(conn)[0].status == "open"


# --- Privacidad ------------------------------------------------------------------------------


def test_el_texto_del_usuario_nunca_llega_al_log(bot, conn, caplog):
    secret = "contraseñaultrasecreta"
    with caplog.at_level(logging.DEBUG):
        bot.say(f"mañana 8am {secret}")
        bot.tap("Recordatorio")
        bot.tap("Sin área")
        bot.tap("Cambiar")
        bot.say("fecha rara de verdad ¿?")
        bot.say(f"{secret} otra cosa")
        bot.say("llamar a Domingo")
    assert secret not in caplog.text
    assert "ultrasecreta" not in caplog.text


def test_hora_de_hoy_a_las_18_se_calcula_en_hora_local(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    bot.tap("Hoy 6:00 pm")
    expected = local_to_utc(__import__("datetime").datetime(2026, 10, 3, 18, 0), TZ)
    assert from_utc_iso(pending(conn)[0].fire_at_utc) == expected


def test_ttl_es_de_10_minutos():
    assert FLOW_TTL == timedelta(minutes=10)


# --- Regla de «¿cuándo?»: ¿respuesta o captura nueva? -----------------------------------------


def waiting_for_when(bot) -> int:
    """Deja el flujo esperando la fecha y devuelve el id de la tarea de bandeja."""
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert "¿Cuándo?" in bot.question[0]
    return all_tasks(bot.conn)[0].id


def test_un_texto_sin_fecha_es_captura_nueva_y_avisa_que_se_descarto_la_pregunta(bot, conn):
    first_id = waiting_for_when(bot)
    bot.say("comprar leche")
    assert handlers.inbox.ABANDONED_TEXT in [t for k, t, _ in bot.channel.log if k == "text"]
    assert [t.title for t in all_tasks(conn)] == ["llamar al dentista", "comprar leche"]
    assert tasks.get_task(conn, first_id).status == "open"  # la primera sigue en la bandeja
    assert pending(conn) == []
    assert bot.labels()[0] == "Tarea"  # y la captura nueva pregunta qué es


def test_hora_dudosa_en_cuando_cuenta_como_respuesta_no_como_captura(bot, conn):
    first_id = waiting_for_when(bot)
    bot.say("mañana a las 9")  # ambiguous_meridiem: 9 am o 9 pm
    assert len(all_tasks(conn)) == 1
    assert "9:00 am" in " ".join(bot.labels()) and "9:00 pm" in " ".join(bot.labels())
    assert handlers.inbox.ABANDONED_TEXT not in [t for k, t, _ in bot.channel.log if k == "text"]
    bot.tap("9:00 am")
    [reminder] = pending(conn)
    assert reminder.text == "llamar al dentista" and local_hhmm(reminder) == "2026-10-04 09:00"
    assert tasks.get_task(conn, first_id).closed_reason == "converted_to_reminder"


def test_candidato_unico_en_cuando_cuenta_como_respuesta_y_se_confirma(bot, conn):
    waiting_for_when(bot)
    bot.say("hoy a las 8")  # a las 15:30 solo queda 8 pm: candidato único
    assert len(all_tasks(conn)) == 1 and pending(conn) == []  # no se guarda en silencio
    bot.tap("8:00 pm")
    [reminder] = pending(conn)
    assert reminder.text == "llamar al dentista" and local_hhmm(reminder) == "2026-10-03 20:00"


# --- «¿Cuándo?» más usable ---------------------------------------------------------------------


def test_cuando_invita_a_escribir_la_hora_con_ejemplos(bot):
    waiting_for_when(bot)
    text = bot.question[0]
    assert text.startswith("¿Cuándo?")
    assert "o escribe cuándo" in text
    assert '"en 2 horas"' in text and '"el viernes a las 5"' in text


def test_el_aviso_de_hora_pasada_tambien_invita_a_escribir(bot, clock):
    clock.advance(hours=2, minutes=25)  # 17:55
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    hoy = bot.choice_id("Hoy 6:00 pm")
    clock.advance(minutes=6)
    bot.press(hoy)
    assert "Esa hora ya pasó. ¿Cuándo?" in bot.question[0]
    assert "o escribe cuándo" in bot.question[0]
    assert "Mejor como tarea" in bot.labels()


def test_mejor_como_tarea_conserva_el_area_y_no_crea_recordatorio(bot, conn):
    first_id = waiting_for_when_in(bot, "iglesia")
    bot.tap("Mejor como tarea")
    assert pending(conn) == []
    task = tasks.get_task(conn, first_id)
    assert (task.status, task.closed_reason) == ("open", None)
    assert task.area_id == areas.find_area_by_name(conn, "iglesia").id
    assert "Tarea guardada en iglesia" in bot.last[1]
    assert bot.conversation.current(bot.clock) is None


def test_mejor_como_tarea_sin_area(bot, conn):
    first_id = waiting_for_when_in(bot, "Sin área")
    bot.tap("Mejor como tarea")
    task = tasks.get_task(conn, first_id)
    assert (task.status, task.area_id) == ("open", None)
    assert pending(conn) == [] and notes.list_notes(conn) == []


def test_mejor_como_tarea_dos_veces_no_da_error(bot, conn):
    waiting_for_when_in(bot, "personal")
    button = bot.choice_id("Mejor como tarea")
    bot.press(button)
    bot.press(button)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert len(all_tasks(conn)) == 1 and pending(conn) == []


def test_mejor_como_tarea_tambien_sirve_tras_cambiar(bot, conn):
    old = confirmed(bot)
    bot.tap("Cambiar")
    bot.tap("Mejor como tarea")
    assert reminders.get_reminder(conn, old.id).status == "cancelled"
    assert pending(conn) == []
    [task] = all_tasks(conn)
    assert (task.status, task.closed_reason) == ("open", None)


def waiting_for_when_in(bot, area_label: str) -> int:
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap(area_label)
    return all_tasks(bot.conn)[0].id


def test_la_confirmacion_sin_hora_dice_hora_por_defecto(bot):
    bot.say("mañana comprar pan")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert "domingo 4 de octubre, 9:00 am (hora por defecto)" in bot.question[0]


def test_la_confirmacion_con_hora_no_dice_hora_por_defecto(bot):
    confirmed(bot)
    assert "hora por defecto" not in bot.question[0]


def test_los_botones_de_la_pregunta_anterior_no_valen_para_la_siguiente_en_el_mismo_paso(bot, conn):
    """Dos preguntas seguidas de «¿cuándo?»: el índice del candidato se reutiliza, así que el id
    del flujo es lo único que impide que un botón viejo apunte a la fecha de la pregunta nueva."""
    waiting_for_when(bot)
    bot.say("mañana a las 9")  # pregunta 1: [9:00 am] [9:00 pm]
    old_nine_am = bot.choice_id("9:00 am")
    bot.say("hoy a las 8")  # pregunta 2: un solo candidato, el índice 0 es otra fecha (8 pm hoy)
    bot.press(old_nine_am)
    assert pending(conn) == []  # el botón viejo NO creó el recordatorio de las 8 pm
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    bot.tap("8:00 pm")  # el botón vigente sí
    assert local_hhmm(pending(conn)[0]) == "2026-10-03 20:00"
