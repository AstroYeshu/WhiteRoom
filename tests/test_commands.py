"""Bloque 7b: /hoy, /pendientes, /recordatorios, /recordar, /tarea, /nota, /areas, /nuevaarea.

Reloj: sábado 2026-10-03 15:30 en México ("mañana" = domingo 4 de octubre).
"""

import logging
from datetime import datetime, timedelta

import pytest

from asistente.bot import commands, handlers
from asistente.core import areas, notes, reminders, tasks
from asistente.timeutil import local_to_utc, to_utc_iso
from tests.botkit import TZ, Bot, module_loop  # noqa: F401


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


def area_id(conn, name: str) -> int:
    found = areas.find_area_by_name(conn, name)
    assert found is not None
    return found.id


def add_task(conn, clock, title, due: str | None = None, area: str | None = None) -> tasks.Task:
    """Una tarea con fecha SIN avisos de preparación (así no ensucian /hoy)."""
    task = tasks.create_task(conn, title, clock, area_id=area_id(conn, area) if area else None)
    if due:
        with conn:
            conn.execute(
                "UPDATE tasks SET due_at_utc = ? WHERE id = ?", (to_utc_iso(local(due)), task.id)
            )
    return task


def add_reminder(conn, clock, text, when: str, area: str | None = None, rrule=None):
    return reminders.create_reminder(
        conn,
        text,
        local(when),
        clock,
        area_id=area_id(conn, area) if area else None,
        rrule=rrule,
    )


def stop(conn, reminder_id: int, code: str) -> None:
    with conn:
        conn.execute("UPDATE reminders SET stop_reason = ? WHERE id = ?", (code, reminder_id))


# --- /hoy --------------------------------------------------------------------------------------


def test_hoy_sin_nada(bot):
    text = bot.reply("/hoy")
    assert text == "Hoy, sábado 3 de octubre\nNo tienes nada para hoy."


def test_hoy_muestra_tareas_vencidas_de_hoy_y_recordatorios_de_hoy(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_task(conn, clock, "pagar luz", "2026-10-02 17:00")
    add_task(conn, clock, "tarea de mañana", "2026-10-04 09:00")
    add_task(conn, clock, "sin fecha")
    add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00")
    add_reminder(conn, clock, "recordatorio de mañana", "2026-10-04 08:00")
    assert bot.reply("/hoy") == (
        "Hoy, sábado 3 de octubre\n"
        "Tareas:\n"
        "- pagar luz (vencida: viernes 2 de octubre, 5:00 pm)\n"
        "- entregar informe (hoy, 5:00 pm) [universidad]\n"
        "Recordatorios:\n"
        "- 6:00 pm: llamar a mamá\n"
        "3 en bandeja sin área"
    )


def test_hoy_con_area_filtra_y_no_muestra_la_bandeja(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_task(conn, clock, "regar plantas", "2026-10-03 17:00", "personal")
    add_reminder(conn, clock, "clase", "2026-10-03 19:00", "universidad")
    add_reminder(conn, clock, "gimnasio", "2026-10-03 19:00", "personal")
    add_task(conn, clock, "suelta")
    text = bot.reply("/hoy Universidad")
    assert "entregar informe" in text and "clase" in text
    assert "regar plantas" not in text and "gimnasio" not in text
    assert "bandeja" not in text


def test_hoy_con_un_area_que_no_existe(bot):
    assert bot.reply("/hoy inventada") == (
        "No encuentro el área «inventada». Escribe /areas para ver las que hay."
    )


def test_hoy_no_cuenta_la_bandeja_si_esta_vacia(bot, conn, clock):
    add_reminder(conn, clock, "llamar", "2026-10-03 18:00")
    assert "bandeja" not in bot.reply("/hoy")


def test_hoy_cerca_de_medianoche_el_dia_termina_a_las_00_00_locales(bot, conn, clock):
    clock.current = local("2026-10-03 23:50")
    add_task(conn, clock, "justo antes", "2026-10-03 23:59")
    add_task(conn, clock, "justo a medianoche", "2026-10-04 00:00")
    add_task(conn, clock, "ya es mañana", "2026-10-04 00:30")
    add_reminder(conn, clock, "aviso de hoy", "2026-10-03 23:55")
    add_reminder(conn, clock, "aviso de mañana", "2026-10-04 00:05")
    text = bot.reply("/hoy")
    assert "justo antes (hoy, 11:59 pm)" in text and "23:55" not in text
    assert "11:55 pm: aviso de hoy" in text
    assert "justo a medianoche" not in text and "ya es mañana" not in text
    assert "aviso de mañana" not in text


def test_hoy_pasada_la_medianoche_ya_es_otro_dia(bot, conn, clock):
    clock.current = local("2026-10-04 00:10")
    add_task(conn, clock, "de anoche", "2026-10-03 23:59")
    add_task(conn, clock, "recién empezado", "2026-10-04 00:05")
    add_task(conn, clock, "fin del día", "2026-10-04 23:59")
    add_task(conn, clock, "mañana a las 00", "2026-10-05 00:00")
    text = bot.reply("/hoy")
    assert text.startswith("Hoy, domingo 4 de octubre\n")
    assert "de anoche (vencida: sábado 3 de octubre, 11:59 pm)" in text
    assert "recién empezado (hoy, 12:05 am)" in text
    assert "fin del día (hoy, 11:59 pm)" in text
    assert "mañana a las 00" not in text


# --- /pendientes ---------------------------------------------------------------------------------


def test_pendientes_sin_tareas(bot):
    assert bot.reply("/pendientes") == "No tienes tareas pendientes."


def test_pendientes_un_mensaje_por_tarea_con_hecha_y_descartar(bot, conn, clock):
    add_task(conn, clock, "sin fecha")
    add_task(conn, clock, "con fecha", "2026-10-04 09:00", "universidad")
    done = add_task(conn, clock, "ya hecha")
    tasks.mark_done(conn, done.id, clock)
    bot.say("/pendientes")
    messages = bot.messages()
    assert messages[0] == "Pendientes (2):"
    assert messages[1] == "con fecha [universidad] (vence: domingo 4 de octubre, 9:00 am)"
    assert messages[2] == "sin fecha"
    buttons = bot.buttons_of("con fecha")
    assert list(buttons) == ["Hecha", "Descartar"]


def test_pendientes_con_area(bot, conn, clock):
    add_task(conn, clock, "de la uni", area="universidad")
    add_task(conn, clock, "personal", area="personal")
    bot.say("/pendientes universidad")
    assert bot.messages() == ["Pendientes (1):", "de la uni [universidad]"]


def test_pendientes_con_un_area_que_no_existe(bot):
    assert "No encuentro el área" in bot.reply("/pendientes nada")


def test_pendientes_limita_la_lista_y_avisa(bot, conn, clock):
    for number in range(commands.PENDING_LIMIT + 3):
        add_task(conn, clock, f"tarea {number}")
    bot.say("/pendientes")
    assert len(bot.messages()) == 1 + commands.PENDING_LIMIT + 1
    assert bot.messages()[0] == f"Pendientes ({commands.PENDING_LIMIT + 3}):"
    assert bot.messages()[-1] == "Hay 3 más. Filtra por área: /pendientes nombre."


def test_hecha_cierra_la_tarea_y_edita_el_mensaje(bot, conn, clock):
    task = add_task(conn, clock, "comprar pan")
    bot.say("/pendientes")
    bot.press(bot.buttons_of("comprar pan")["Hecha"])
    assert tasks.get_task(conn, task.id).status == "done"
    assert bot.edits() == ["Hecha: comprar pan"]


def test_descartar_es_soft_delete_con_motivo(bot, conn, clock):
    task = add_task(conn, clock, "comprar pan")
    bot.say("/pendientes")
    bot.press(bot.buttons_of("comprar pan")["Descartar"])
    stored = tasks.get_task(conn, task.id)
    assert (stored.status, stored.closed_reason) == ("dropped", "discarded")
    assert bot.edits() == ["Descartada: comprar pan"]


def test_pulsar_dos_veces_o_en_otra_tarea_cerrada_no_da_error(bot, conn, clock):
    task = add_task(conn, clock, "comprar pan")
    bot.say("/pendientes")
    buttons = bot.buttons_of("comprar pan")
    bot.press(buttons["Hecha"])
    bot.press(buttons["Hecha"])
    bot.press(buttons["Descartar"])
    assert tasks.get_task(conn, task.id).status == "done"  # la segunda pulsación no la cambió
    assert bot.edits()[1:] == ["Esta tarea ya no está abierta: comprar pan"] * 2


def test_hecha_cancela_los_avisos_de_preparacion(bot, conn, clock):
    task = tasks.create_task(conn, "entrega", clock, due_at_utc=local("2026-10-05 09:00"))
    assert reminders.list_pending(conn)  # hay avisos de preparación
    bot.say("/pendientes")
    bot.press(bot.buttons_of("entrega")["Hecha"])
    assert tasks.get_task(conn, task.id).status == "done"
    assert reminders.list_pending(conn) == []


@pytest.mark.parametrize(
    "choice_id", ["tk_done", "tk_done:x", "tk_drop:1:2", "tk_done:99999", "tk_x:1"]
)
def test_botones_de_tarea_mal_formados_o_inexistentes(bot, choice_id):
    bot.press(choice_id)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]


# --- /recordatorios ------------------------------------------------------------------------------


def test_recordatorios_sin_pendientes(bot):
    assert bot.reply("/recordatorios") == "No tienes recordatorios pendientes."


def test_recordatorios_lista_pendientes_con_area_y_repeticion(bot, conn, clock):
    add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00", "universidad")
    add_reminder(conn, clock, "regar plantas", "2026-10-05 19:00", rrule="FREQ=WEEKLY;BYDAY=MO")
    done = add_reminder(conn, clock, "ya hecho", "2026-10-04 07:00")
    reminders.mark_done(conn, done.id)
    assert bot.reply("/recordatorios") == (
        "Recordatorios pendientes (2):\n"
        "- domingo 4 de octubre, 8:00 am: llevar tarea [universidad]\n"
        "- lunes 5 de octubre, 7:00 pm: regar plantas (Cada lunes)"
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("permanent:bot_blocked", "el bot está bloqueado en tu chat"),
        ("permanent:chat_not_found", "no se encontró tu chat"),
        ("permanent:message_too_long", "el mensaje era demasiado largo"),
        ("permanent:bad_request:cant_parse_entities", "Telegram no pudo leer el formato del texto"),
        ("permanent:bad_request:empty_text", "el texto estaba vacío"),
        ("permanent:bad_request:button_data_invalid", "un botón no era válido"),
        ("permanent:bad_request:other", "Telegram rechazó el mensaje"),
        ("horizon:telegram_down", "Telegram no respondió durante 24 horas"),
        ("legacy", "se detuvo en una versión anterior"),
        ("permanent:telegram_error:Conflict", "error inesperado al enviar"),
        ("permanent:unexpected:KeyError", "error inesperado al enviar"),
    ],
)
def test_los_detenidos_se_explican_en_lenguaje_claro(bot, conn, clock, code, expected):
    stopped = add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00")
    stop(conn, stopped.id, code)
    text = bot.reply("/recordatorios")
    assert f"llevar tarea (detenido: {expected})" in text
    assert code not in text  # el código crudo nunca llega al usuario


@pytest.mark.parametrize("code", ["permanent:algo_raro", "horizon:otro", "", "xyz"])
def test_un_codigo_desconocido_dice_motivo_desconocido_y_el_codigo_solo_va_al_log(
    bot, conn, clock, caplog, code
):
    stopped = add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00")
    stop(conn, stopped.id, code)
    with caplog.at_level(logging.WARNING):
        text = bot.reply("/recordatorios")
    assert "llevar tarea (detenido: motivo desconocido)" in text
    if code:
        assert code not in text
        assert code in caplog.text
    assert "llevar tarea" not in caplog.text  # el texto del usuario nunca va al log


def test_stop_reason_text_es_una_funcion_pura():
    assert commands.stop_reason_text("permanent:bot_blocked") == "el bot está bloqueado en tu chat"
    assert commands.stop_reason_text("permanent:otra_cosa") is None


def test_recordatorios_limita_la_lista(bot, conn, clock):
    for number in range(commands.REMINDERS_LIMIT + 2):
        add_reminder(conn, clock, f"r{number}", "2026-10-04 08:00")
    text = bot.reply("/recordatorios")
    assert text.endswith("...y 2 más.")
    assert text.count("\n- ") == commands.REMINDERS_LIMIT


# --- /recordar -----------------------------------------------------------------------------------


def test_recordar_sin_texto_explica_como_usarlo(bot):
    assert bot.reply("/recordar") == (
        "Escribe /recordar seguido de qué y cuándo, por ejemplo: /recordar mañana 8 am llevar tarea"
    )


def test_recordar_muestra_la_interpretacion_antes_de_guardar(bot, conn, clock):
    bot.say("/recordar mañana 8am llevar tarea")
    assert "¿En qué área" in bot.question[0]  # ya es recordatorio: no pregunta el tipo
    bot.tap("universidad")
    text, _ = bot.question
    assert text == (
        "Recordatorio: «llevar tarea»\n"
        "Cuándo: domingo 4 de octubre, 8:00 am\n"
        "Área: universidad\n"
        "¿Lo guardo?"
    )
    assert bot.labels() == ["Guardar", "Cancelar"]
    assert reminders.list_pending(conn) == []  # todavía no se guardó
    bot.tap("Guardar")
    [reminder] = reminders.list_pending(conn)
    assert reminder.text == "llevar tarea" and reminder.area_id == area_id(conn, "universidad")
    assert bot.labels() == ["Cambiar", "Deshacer"]


def test_recordar_con_repeticion_muestra_interpretacion_y_proxima_fecha(bot, conn):
    bot.say("/recordar todos los lunes a las 7 pm regar plantas")
    bot.tap("Sin área")
    text, _ = bot.question
    assert "Repetición: Cada lunes" in text and "Próxima: lunes 5 de octubre, 7:00 pm" in text
    assert reminders.list_pending(conn) == []
    bot.tap("Guardar")
    assert reminders.list_pending(conn)[0].rrule == "FREQ=WEEKLY;BYDAY=MO"


def test_recordar_cancelar_deja_la_tarea_en_la_bandeja(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea")
    bot.tap("Sin área")
    bot.tap("Cancelar")
    assert reminders.list_pending(conn) == []
    [row] = conn.execute("SELECT status, area_id FROM tasks").fetchall()
    assert (row["status"], row["area_id"]) == ("open", None)


def test_recordar_sin_fecha_pregunta_cuando(bot, conn):
    bot.say("/recordar llamar al dentista")
    bot.tap("Sin área")
    assert "¿Cuándo?" in bot.question[0]
    bot.tap("Mañana 9:00 am")
    assert reminders.list_pending(conn) == []  # /recordar siempre muestra antes de guardar
    assert "¿Lo guardo?" in bot.question[0]
    bot.tap("Guardar")
    assert reminders.list_pending(conn)[0].text == "llamar al dentista"


def test_recordar_con_una_pregunta_del_parser_pide_pulsar_el_candidato(bot, conn):
    bot.say("/recordar mañana a las 9 llevar tarea")
    bot.tap("Sin área")
    assert reminders.list_pending(conn) == []
    bot.tap("9:00 pm")
    assert "¿Lo guardo?" in bot.question[0]
    bot.tap("Guardar")
    assert reminders.list_pending(conn)[0].text == "llevar tarea"


def test_recordar_guarda_primero_en_la_bandeja(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea")
    assert [
        t.title
        for t in map(lambda r: tasks.get_task(conn, r["id"]), conn.execute("SELECT id FROM tasks"))
    ] == ["mañana 8am llevar tarea"]


# --- /tarea y /nota ------------------------------------------------------------------------------


def test_tarea_sin_texto_explica_como_usarla(bot):
    assert (
        bot.reply("/tarea") == "Escribe /tarea seguido de la tarea, por ejemplo: /tarea comprar pan"
    )


def test_nota_sin_texto_explica_como_usarla(bot):
    assert bot.reply("/nota") == (
        "Escribe /nota seguido de la nota, por ejemplo: /nota la clave del wifi está en el router"
    )


def test_tarea_solo_pregunta_el_area(bot, conn):
    bot.say("/tarea comprar pan")
    assert "¿En qué área" in bot.question[0]
    bot.tap("personal")
    [task] = [tasks.get_task(conn, r["id"]) for r in conn.execute("SELECT id FROM tasks")]
    assert (task.title, task.status, task.area_id) == (
        "comprar pan",
        "open",
        area_id(conn, "personal"),
    )
    assert "Tarea guardada en personal" in bot.last[1]


def test_tarea_con_texto_de_recordatorio_no_se_convierte_en_recordatorio(bot, conn):
    bot.say("/tarea recuérdame mañana 8am llevar tarea")
    bot.tap("Sin área")
    bot.tap("No")  # la fecha del texto se ofrece como fecha límite; aquí no lo es
    assert reminders.list_pending(conn) == []
    assert "Tarea guardada" in bot.last[1]


def test_nota_solo_pregunta_el_area(bot, conn):
    bot.say("/nota la clave del wifi")
    bot.tap("personal")
    [note] = notes.list_notes(conn)
    assert (note.text, note.area_id) == ("la clave del wifi", area_id(conn, "personal"))
    [task] = [tasks.get_task(conn, r["id"]) for r in conn.execute("SELECT id FROM tasks")]
    assert task.closed_reason == "converted_to_note"


def test_tarea_a_mitad_de_otra_pregunta_descarta_la_anterior_y_avisa(bot, conn):
    bot.say("comprar leche")
    bot.say("/tarea sacar copias")
    assert any("sin terminar" in message for message in bot.messages())
    bot.tap("Sin área")
    titles = [r["title"] for r in conn.execute("SELECT title FROM tasks ORDER BY id")]
    assert titles == ["comprar leche", "sacar copias"]


# --- /areas y /nuevaarea -------------------------------------------------------------------------


def test_areas_lista_y_marca_las_que_no_tienen_descripcion(bot, conn, clock):
    areas.create_area(conn, "Salud", "", clock)
    text = bot.reply("/areas")
    assert text.startswith("Áreas:\n- universidad\n")
    assert "- Salud (sin descripción)" in text
    assert "- universidad (sin descripción)" not in text


def test_areas_no_lista_las_archivadas(bot, conn):
    areas.archive_area(conn, area_id(conn, "iglesia"))
    assert "iglesia" not in bot.reply("/areas")


def test_nuevaarea_sin_nombre_explica_como_usarla(bot):
    assert bot.reply("/nuevaarea") == (
        "Escribe /nuevaarea seguido del nombre, por ejemplo: /nuevaarea Salud"
    )


def test_nuevaarea_pregunta_la_descripcion_con_omitir(bot, conn):
    bot.say("/nuevaarea Salud")
    text, _ = bot.question
    assert text == "¿Qué cubre «Salud»? Escribe una descripción corta u omítela."
    assert bot.labels() == ["Omitir", "Cancelar"]
    assert areas.find_area_by_name(conn, "Salud") is None  # aún no existe
    bot.say("Ejercicio y citas médicas")
    created = areas.find_area_by_name(conn, "Salud")
    assert created is not None and created.description == "Ejercicio y citas médicas"
    assert bot.last[1] == "Área creada: Salud"


def test_nuevaarea_omitir_la_crea_sin_descripcion(bot, conn):
    bot.say("/nuevaarea Salud")
    bot.tap("Omitir")
    created = areas.find_area_by_name(conn, "Salud")
    assert created is not None and created.description == ""
    assert bot.edits()[-1] == "Área creada: Salud (sin descripción)"


def test_nuevaarea_cancelar_no_crea_nada(bot, conn):
    bot.say("/nuevaarea Salud")
    bot.tap("Cancelar")
    assert areas.find_area_by_name(conn, "Salud") is None
    assert bot.edits()[-1] == "Cancelado. No se creó el área."


@pytest.mark.parametrize("name", ["universidad", "UNIVERSIDAD", "Universidád"])
def test_nuevaarea_con_nombre_repetido_avisa_antes_de_preguntar(bot, conn, name):
    before = len(areas.list_areas(conn))
    text = bot.reply(f"/nuevaarea {name}")
    assert text == "Ya existe un área llamada «universidad»."
    assert len(areas.list_areas(conn)) == before
    assert bot.conversation.current(bot.clock) is None


def test_nuevaarea_con_nombre_demasiado_largo(bot):
    assert "demasiado largo" in bot.reply("/nuevaarea " + "x" * 41)


def test_nuevaarea_si_el_nombre_se_ocupa_mientras_tanto_avisa(bot, conn, clock):
    bot.say("/nuevaarea Salud")
    areas.create_area(
        conn, "salud", "otra", clock
    )  # alguien la creó entre la pregunta y la respuesta
    bot.say("Ejercicio")
    assert bot.last[1] == "Ya existe un área llamada «salud»."


def test_un_comando_a_mitad_de_nuevaarea_no_se_toma_como_descripcion(bot, conn):
    bot.say("/nuevaarea Salud")
    assert "Hoy, sábado" in bot.reply("/hoy")
    bot.say("Ejercicio")  # el flujo sigue vivo: esto sí es la descripción
    assert areas.find_area_by_name(conn, "Salud").description == "Ejercicio"


def test_la_descripcion_caduca_a_los_10_minutos(bot, conn, clock):
    bot.say("/nuevaarea Salud")
    clock.advance(minutes=11)
    bot.say("comprar leche")  # ya no es la descripción: es una captura nueva
    assert areas.find_area_by_name(conn, "Salud") is None
    assert bot.labels()[0] == "Tarea"


def test_un_boton_viejo_de_nuevaarea_no_crea_nada(bot, conn):
    bot.say("/nuevaarea Salud")
    old = bot.choice_id("Omitir")
    bot.say("/nuevaarea Deportes")
    bot.press(old)
    assert areas.find_area_by_name(conn, "Salud") is None
    assert areas.find_area_by_name(conn, "Deportes") is None


# --- /ayuda y seguridad --------------------------------------------------------------------------


def test_ayuda_lista_todos_los_comandos_y_no_la_papelera(bot):
    text = bot.reply("/ayuda")
    for command in (
        "/hoy",
        "/pendientes",
        "/recordatorios",
        "/recordar",
        "/tarea",
        "/nota",
        "/areas",
        "/nuevaarea",
        "/ayuda",
        "/start",
    ):
        assert command in text
    assert "/papelera" not in text
    assert text == handlers.HELP_TEXT


@pytest.mark.parametrize(
    "text",
    [
        "/hoy",
        "/pendientes",
        "/recordatorios",
        "/recordar mañana 8am x",
        "/tarea x",
        "/nota x",
        "/areas",
        "/nuevaarea Salud",
    ],
)
def test_un_extrano_no_recibe_nada_ni_cambia_nada(bot, conn, text):
    bot.say(text, user=99999)
    assert bot.channel.sent_anything is False
    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_los_comandos_no_registran_el_texto_del_usuario(bot, conn, clock, caplog):
    secret = "secretoultraprivado"
    with caplog.at_level(logging.DEBUG):
        bot.say(f"/tarea {secret}")
        bot.tap("Sin área")
        bot.say(f"/nota {secret}")
        bot.tap("Sin área")
        bot.say(f"/recordar mañana 8am {secret}")
        bot.tap("Sin área")
        bot.tap("Guardar")
        bot.say(f"/hoy {secret}")
        bot.say("/pendientes")
        bot.say("/recordatorios")
        bot.say(f"/nuevaarea {secret}")
        bot.say(secret)
    assert secret not in caplog.text


def test_el_tiempo_de_un_dia_cercano_a_medianoche_usa_la_zona_del_usuario(bot, conn, clock):
    """23:59 locales de hoy son las 05:59 UTC de mañana: el filtro debe ser local, no UTC."""
    clock.current = local("2026-10-03 20:00")
    add_task(conn, clock, "tarde", "2026-10-03 23:59")
    assert "tarde (hoy, 11:59 pm)" in bot.reply("/hoy")
    assert timedelta(0) < local("2026-10-03 23:59") - clock.current < timedelta(hours=5)


# --- /tarea con fecha límite --------------------------------------------------------------------


def task_with_deadline(bot, text: str = "/tarea entregar informe el viernes"):
    bot.say(text)
    bot.tap("Sin área")


def only_task(conn) -> tasks.Task:
    [row] = conn.execute("SELECT id FROM tasks").fetchall()
    return tasks.get_task(conn, row["id"])


def test_tarea_con_fecha_pregunta_si_es_la_fecha_limite_despues_del_area(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    assert "¿En qué área" in bot.question[0]
    bot.tap("universidad")
    text, _ = bot.question
    assert text == (
        "¿Es la fecha límite de «entregar informe»?\n"
        "Fecha: viernes 9 de octubre, 9:00 am (hora por defecto)"
    )
    assert bot.labels() == ["Sí", "No", "Cancelar"]
    task = only_task(conn)
    assert task.due_at_utc is None and task.status == "open"  # aún no se decidió


def test_si_pone_la_fecha_limite_limpia_el_titulo_y_crea_los_avisos_de_preparacion(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    bot.tap("universidad")
    bot.tap("Sí")
    task = only_task(conn)
    assert task.title == "entregar informe"
    assert task.due_at_utc == to_utc_iso(local("2026-10-09 09:00"))
    assert (task.status, task.area_id) == ("open", area_id(conn, "universidad"))
    assert task.source_text == "entregar informe el viernes"  # lo original se conserva
    assert len(reminders.list_pending(conn)) == 2  # 1 día y 1 hora antes
    assert bot.edits()[-1] == (
        "Tarea guardada en universidad: «entregar informe» (vence: viernes 9 de octubre, 9:00 am)"
    )


def test_no_deja_la_tarea_con_el_texto_completo_y_sin_fecha(bot, conn):
    task_with_deadline(bot)
    bot.tap("No")
    task = only_task(conn)
    assert task.title == "entregar informe el viernes" and task.due_at_utc is None
    assert reminders.list_pending(conn) == []
    assert bot.edits()[-1] == "Tarea guardada: «entregar informe el viernes»"


def test_cancelar_la_pregunta_deja_la_tarea_en_la_bandeja(bot, conn):
    task_with_deadline(bot)
    bot.tap("Cancelar")
    task = only_task(conn)
    assert (task.title, task.due_at_utc, task.status) == (
        "entregar informe el viernes",
        None,
        "open",
    )


def test_con_una_fecha_dudosa_no_se_pregunta_nada(bot, conn):
    bot.say("/tarea llamar mañana a las 9")  # ambiguous_meridiem: no se adivina
    bot.tap("Sin área")
    assert "Tarea guardada" in bot.last[1]
    assert only_task(conn).due_at_utc is None


def test_sin_fecha_no_se_pregunta_nada(bot, conn):
    bot.say("/tarea comprar pan")
    bot.tap("Sin área")
    assert "Tarea guardada" in bot.last[1]


def test_el_texto_libre_con_fecha_no_pregunta_por_fecha_limite(bot, conn):
    bot.say("entregar informe el viernes")
    bot.tap("Tarea")
    bot.tap("Sin área")
    assert "Tarea guardada" in bot.last[1]
    assert only_task(conn).due_at_utc is None


def test_pulsar_si_dos_veces_no_da_error_ni_duplica_avisos(bot, conn):
    task_with_deadline(bot)
    yes = bot.choice_id("Sí")
    bot.press(yes)
    bot.press(yes)
    assert handlers.STALE_CHOICE_TEXT in bot.last[1]
    assert len(reminders.list_pending(conn)) == 2


def test_sin_areas_la_pregunta_de_fecha_limite_sale_igual(bot, conn):
    for area in areas.list_areas(conn):
        areas.archive_area(conn, area.id)
    bot.say("/tarea entregar informe el viernes")
    assert "fecha límite" in bot.question[0]
    bot.tap("Sí")
    assert only_task(conn).due_at_utc == to_utc_iso(local("2026-10-09 09:00"))


def test_set_title_cambia_solo_el_titulo(conn, clock):
    task = tasks.create_task(conn, "viejo", clock, source_text="viejo")
    tasks.set_title(conn, task.id, "nuevo", clock)
    stored = tasks.get_task(conn, task.id)
    assert (stored.title, stored.source_text) == ("nuevo", "viejo")
