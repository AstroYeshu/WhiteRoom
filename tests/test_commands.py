"""Bloque 7b: /hoy, /pendientes, /recordatorios, /recordar, /tarea, /nota, /areas, /nuevaarea.

Reloj: sábado 2026-10-03 15:30 en México ("mañana" = domingo 4 de octubre).
"""

import logging
from datetime import datetime

import pytest

from asistente import formato as fmt
from asistente.bot import commands
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


# --- /pendientes ---------------------------------------------------------------------------------


# --- /recordatorios ------------------------------------------------------------------------------


def test_stop_reason_text_es_una_funcion_pura():
    assert commands.stop_reason_text("permanent:bot_blocked") == "el bot está bloqueado en tu chat"
    assert commands.stop_reason_text("permanent:otra_cosa") is None


# --- /recordar -----------------------------------------------------------------------------------


def test_recordar_muestra_la_interpretacion_antes_de_guardar(bot, conn, clock):
    bot.say("/recordar mañana 8am llevar tarea")
    assert "¿En qué área" in bot.question[0]  # ya es recordatorio: no pregunta el tipo
    bot.tap("Universidad")
    text, _ = bot.question
    assert fmt.plain(text) == (
        "¿Guardo este recordatorio?\n\nLlevar tarea\n\n"
        "Cuándo: domingo 4 de octubre, 8:00 am\nÁrea: Universidad"
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
    assert "¿Guardo este recordatorio?" in bot.question[0]
    bot.tap("Guardar")
    assert reminders.list_pending(conn)[0].text == "llamar al dentista"


def test_recordar_con_una_pregunta_del_parser_pide_pulsar_el_candidato(bot, conn):
    bot.say("/recordar mañana a las 9 llevar tarea")
    bot.tap("Sin área")
    assert reminders.list_pending(conn) == []
    bot.tap("9:00 pm")
    assert "¿Guardo este recordatorio?" in bot.question[0]
    bot.tap("Guardar")
    assert reminders.list_pending(conn)[0].text == "llevar tarea"


def test_recordar_guarda_primero_en_la_bandeja(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea")
    assert [
        t.title
        for t in map(lambda r: tasks.get_task(conn, r["id"]), conn.execute("SELECT id FROM tasks"))
    ] == ["mañana 8am llevar tarea"]


# --- /tarea y /nota ------------------------------------------------------------------------------


def test_tarea_solo_pregunta_el_area(bot, conn):
    bot.say("/tarea comprar pan")
    assert "¿En qué área" in bot.question[0]
    bot.tap("Personal")
    [task] = [tasks.get_task(conn, r["id"]) for r in conn.execute("SELECT id FROM tasks")]
    assert (task.title, task.status, task.area_id) == (
        "comprar pan",
        "open",
        area_id(conn, "personal"),
    )
    assert fmt.plain(bot.last[1]) == "Tarea guardada\n\nComprar pan\n\nÁrea: Personal"


def test_tarea_con_texto_de_recordatorio_no_se_convierte_en_recordatorio(bot, conn):
    bot.say("/tarea recuérdame mañana 8am llevar tarea")
    bot.tap("Sin área")
    bot.tap("No")  # la fecha del texto se ofrece como fecha límite; aquí no lo es
    assert reminders.list_pending(conn) == []
    assert "Tarea guardada" in bot.last[1]


def test_nota_solo_pregunta_el_area(bot, conn):
    bot.say("/nota la clave del wifi")
    bot.tap("Personal")
    [note] = notes.list_notes(conn)
    assert (note.text, note.area_id) == ("la clave del wifi", area_id(conn, "personal"))
    [task] = [tasks.get_task(conn, r["id"]) for r in conn.execute("SELECT id FROM tasks")]
    assert task.closed_reason == "converted_to_note"


def test_tarea_a_mitad_de_otra_pregunta_descarta_la_anterior_y_avisa(bot, conn):
    bot.say("comprar leche")
    bot.say("/tarea sacar copias")
    first = fmt.plain(bot.text_of(bot.channel.refs[0]))  # la tarjeta vieja se editó
    assert first.startswith("Sin terminar\n\nComprar leche")
    bot.tap("Sin área")
    titles = [r["title"] for r in conn.execute("SELECT title FROM tasks ORDER BY id")]
    assert titles == ["comprar leche", "sacar copias"]


# --- /areas y /nuevaarea -------------------------------------------------------------------------


def test_nuevaarea_pregunta_la_descripcion_con_omitir(bot, conn):
    bot.say("/nuevaarea Salud")
    text, _ = bot.question
    assert fmt.plain(text) == "¿Qué cubre «Salud»?\n\nEscribe una descripción corta u omítela."
    assert bot.labels() == ["Omitir", "Cancelar"]
    assert areas.find_area_by_name(conn, "Salud") is None  # aún no existe
    bot.say("Ejercicio y citas médicas")
    created = areas.find_area_by_name(conn, "Salud")
    assert created is not None and created.description == "Ejercicio y citas médicas"
    assert fmt.plain(bot.last[1]) == "Área guardada\n\nSalud\n\nEjercicio y citas médicas"


def test_nuevaarea_omitir_la_crea_sin_descripcion(bot, conn):
    bot.say("/nuevaarea Salud")
    bot.tap("Omitir")
    created = areas.find_area_by_name(conn, "Salud")
    assert created is not None and created.description == ""
    assert fmt.plain(bot.edits()[-1]) == "Área guardada\n\nSalud\n\nSin descripción."


def test_nuevaarea_cancelar_no_crea_nada(bot, conn):
    bot.say("/nuevaarea Salud")
    bot.tap("Cancelar")
    assert areas.find_area_by_name(conn, "Salud") is None
    assert fmt.plain(bot.edits()[-1]) == "Cancelado\n\nSalud\n\nNo se creó el área."


@pytest.mark.parametrize("name", ["universidad", "UNIVERSIDAD", "Universidád"])
def test_nuevaarea_con_nombre_repetido_avisa_antes_de_preguntar(bot, conn, name):
    before = len(areas.list_areas(conn))
    text = bot.reply(f"/nuevaarea {name}")
    assert fmt.plain(text) == "Aviso · Ya existe un área llamada «Universidad»."
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
    assert fmt.plain(bot.last[1]) == "Aviso · Ya existe un área llamada «Salud»."


def test_un_comando_a_mitad_de_nuevaarea_no_se_toma_como_descripcion(bot, conn):
    bot.say("/nuevaarea Salud")
    assert "Hoy · sábado" in fmt.plain(bot.reply("/hoy"))
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
    bot.tap("Universidad")
    text, _ = bot.question
    assert fmt.plain(text) == (
        "¿Es la fecha límite?\n\nEntregar informe\n\n"
        "Tipo: Tarea\nÁrea: Universidad\nFecha: viernes 9 de octubre, 9:00 am (hora por defecto)"
    )
    assert bot.labels() == ["Sí", "No", "Cancelar"]
    task = only_task(conn)
    assert task.due_at_utc is None and task.status == "open"  # aún no se decidió


def test_si_pone_la_fecha_limite_limpia_el_titulo_y_crea_los_avisos_de_preparacion(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    bot.tap("Universidad")
    bot.tap("Sí")
    task = only_task(conn)
    assert task.title == "entregar informe"
    assert task.due_at_utc == to_utc_iso(local("2026-10-09 09:00"))
    assert (task.status, task.area_id) == ("open", area_id(conn, "universidad"))
    assert task.source_text == "entregar informe el viernes"  # lo original se conserva
    assert len(reminders.list_pending(conn)) == 2  # 1 día y 1 hora antes
    assert fmt.plain(bot.edits()[-1]) == (
        "Tarea guardada\n\nEntregar informe\n\n"
        "Área: Universidad\nVence: viernes 9 de octubre, 9:00 am (hora por defecto)"
    )


def test_no_deja_la_tarea_con_el_texto_completo_y_sin_fecha(bot, conn):
    task_with_deadline(bot)
    bot.tap("No")
    task = only_task(conn)
    assert task.title == "entregar informe el viernes" and task.due_at_utc is None
    assert reminders.list_pending(conn) == []
    assert fmt.plain(bot.edits()[-1]) == "Tarea guardada\n\nEntregar informe el viernes"


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
    before = len(bot.channel.log)
    assert bot.press(yes) is None  # la doble pulsación no hace nada ni pisa la tarea guardada
    assert len(bot.channel.log) == before
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
