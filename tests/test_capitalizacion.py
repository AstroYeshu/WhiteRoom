"""Commit 1 del estilo: `cap_first` (solo al MOSTRAR) y nombres de área normalizados al crearse.

Reloj: sábado 2026-10-03 15:30 en México. Lo guardado NO se modifica (títulos, textos de
recordatorios, notas, descripciones); solo cambia lo que ve el usuario. Los nombres de área sí
se normalizan al crearlos (primera letra en mayúscula), y la unicidad no distingue mayúsculas
ni acentos.
"""

from datetime import timedelta

import pytest

from asistente import formato as fmt
from asistente.core import areas, notes, reminders, tasks
from tests.botkit import Bot, module_loop  # noqa: F401
from tests.test_commands import add_reminder, add_task
from tests.test_telegram_real import RealPath


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def legacy_area(conn, name: str) -> int:
    """Un área con el nombre EXACTO que se pase (como las que la migración dejó sin tocar)."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO areas (name, description, created_at) VALUES (?, '', 'x')", (name,)
        )
    return cursor.lastrowid


def stored_area_name(conn, wanted_id: int) -> str:
    return conn.execute("SELECT name FROM areas WHERE id = ?", (wanted_id,)).fetchone()["name"]


# --- cap_first -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("comprar leche", "Comprar leche"),
        ("Ya", "Ya"),
        ("123 a", "123 a"),
        ("¿qué?", "¿Qué?"),
        ("¡hola!", "¡Hola!"),
        ("¿¡qué!?", "¿¡Qué!?"),
        ("iOS", "iOS"),
        ("iPhone nuevo", "iPhone nuevo"),
        ("UNAM", "UNAM"),
        ("", ""),
        ("ñandú", "Ñandú"),
        ("álgebra", "Álgebra"),
        ("ébano y marfil", "Ébano y marfil"),
        ("comprar LECHE y Pan", "Comprar LECHE y Pan"),
        ("ß", "ß"),
        ("¿", "¿"),
        ("  hola", "  hola"),
        ("-hola", "-hola"),
        ("3 de oro", "3 de oro"),
    ],
)
def test_cap_first(text, expected):
    assert fmt.cap_first(text) == expected


def test_cap_first_no_toca_el_resto_del_texto():
    assert fmt.cap_first("hola mundo & <b>x</b>") == "Hola mundo & <b>x</b>"


def test_cap_first_es_idempotente():
    for text in ("comprar leche", "¿qué?", "ñandú", "iOS", "123 a"):
        assert fmt.cap_first(fmt.cap_first(text)) == fmt.cap_first(text)


# --- Áreas nuevas: normalizadas al crearse --------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("salud", "Salud"),
        ("  salud   física  ", "Salud física"),
        ("Salud", "Salud"),
        ("iOS", "iOS"),
        ("UNAM", "UNAM"),
        ("ñandú", "Ñandú"),
        ("álgebra lineal", "Álgebra lineal"),
        ("2 casas", "2 casas"),
    ],
)
def test_el_area_nueva_se_guarda_con_la_primera_letra_en_mayuscula(conn, clock, typed, stored):
    created = areas.create_area(conn, typed, "", clock)
    assert created.name == stored
    assert stored_area_name(conn, created.id) == stored


def test_validate_new_name_devuelve_el_nombre_normalizado(conn):
    assert areas.validate_new_name(conn, "  viajes   largos ") == "Viajes largos"


def test_la_descripcion_no_se_capitaliza(conn, clock):
    created = areas.create_area(conn, "salud", "  médico   y gimnasio ", clock)
    assert created.description == "médico y gimnasio"


@pytest.mark.parametrize("duplicate", ["universidad", "UNIVERSIDAD", "Universidad", "universidád"])
def test_la_unicidad_no_distingue_mayusculas_ni_acentos(conn, clock, duplicate):
    with pytest.raises(areas.AreaError, match="Ya existe un área llamada «Universidad»"):
        areas.create_area(conn, duplicate, "", clock)


def test_la_unicidad_sigue_aunque_el_existente_este_en_minuscula(conn, clock):
    legacy_area(conn, "viajes")  # como una que la migración dejó por una colisión
    with pytest.raises(areas.AreaError, match="Ya existe"):
        areas.create_area(conn, "Viajes", "", clock)
    with pytest.raises(areas.AreaError, match="Ya existe"):
        areas.create_area(conn, "VIAJES", "", clock)


def test_la_unicidad_cuenta_a_las_archivadas(conn, clock):
    archived = areas.create_area(conn, "viajes", "", clock)
    areas.archive_area(conn, archived.id)
    with pytest.raises(areas.AreaError, match="Ya existe un área llamada «Viajes» \\(archivada\\)"):
        areas.create_area(conn, "VIAJES", "", clock)


def test_nuevaarea_guarda_el_nombre_en_mayuscula_y_lo_muestra_igual(bot, conn):
    bot.say("/nuevaarea  salud   física")
    assert "¿Qué cubre «Salud física»?" in fmt.plain(bot.question[0])
    bot.tap("Omitir")
    assert fmt.plain(bot.question[0]) != ""  # la tarjeta es la constancia
    created = areas.find_area_by_name(conn, "salud fisica")
    assert created is not None and created.name == "Salud física"
    assert fmt.plain(bot.channel.log[-1][1]).startswith("Área guardada\n\nSalud física")


def test_nuevaarea_con_nombre_repetido_avisa_con_el_nombre_guardado(bot):
    text = fmt.plain(bot.reply("/nuevaarea UNIVERSIDAD"))
    assert text == "Aviso · Ya existe un área llamada «Universidad»."


@pytest.mark.parametrize("typed", ["universidad", "Universidad", "UNIVERSIDAD", "universidád"])
def test_pendientes_acepta_cualquier_capitalizacion_del_area(bot, conn, clock, typed):
    add_task(conn, clock, "entregar informe", None, "universidad")
    add_task(conn, clock, "regar plantas", None, "personal")
    text = fmt.plain(bot.reply(f"/pendientes {typed}"))
    assert text.startswith("Pendientes · Universidad (1)")
    assert "Entregar informe" in text and "Regar plantas" not in text


@pytest.mark.parametrize("typed", ["universidad", "UNIVERSIDAD", "Universidad"])
def test_hoy_acepta_cualquier_capitalizacion_del_area(bot, conn, clock, typed):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    text = fmt.plain(bot.reply(f"/hoy {typed}"))
    assert text.startswith("Hoy · sábado 3 de octubre · Universidad\n")
    assert "Entregar informe" in text


def test_un_area_que_no_existe_repite_lo_escrito_tal_cual(bot):
    text = fmt.plain(bot.reply("/pendientes nada"))
    assert text == "Aviso · No encuentro el área «nada». Escribe /areas para ver las que hay."


# --- Lo guardado NO cambia: solo lo mostrado ------------------------------------------------------


def test_la_tarea_guardada_conserva_su_minuscula(bot, conn):
    bot.say("comprar leche")
    bot.tap("Tarea")
    bot.tap("Personal")
    [row] = conn.execute("SELECT title, source_text FROM tasks").fetchall()
    assert (row["title"], row["source_text"]) == ("comprar leche", "comprar leche")
    assert fmt.plain(bot.channel.log[-1][1]) == "Tarea guardada\n\nComprar leche\n\nÁrea: Personal"


def test_la_nota_guardada_conserva_su_minuscula(bot, conn):
    bot.say("/nota la clave del wifi está en el router")
    bot.tap("Personal")
    [note] = notes.list_notes(conn)
    assert note.text == "la clave del wifi está en el router"
    assert fmt.plain(bot.channel.log[-1][1]).startswith("Nota guardada\n\nLa clave del wifi")


def test_el_recordatorio_guardado_conserva_su_minuscula(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea")
    bot.tap("Universidad")
    assert fmt.plain(bot.question[0]).startswith("¿Guardo este recordatorio?\n\nLlevar tarea\n\n")
    bot.tap("Guardar")
    [reminder] = reminders.list_pending(conn)
    assert reminder.text == "llevar tarea"
    assert fmt.plain(bot.channel.log[-1][1]).startswith("Recordatorio guardado\n\nLlevar tarea")


def test_la_etiqueta_de_clasificacion_guarda_el_texto_y_el_area_sin_cambiar(bot, conn):
    bot.say("comprar leche")
    bot.tap("Tarea")
    bot.tap("Personal")
    [row] = conn.execute("SELECT text_norm, final_area FROM classification_log").fetchall()
    assert row["text_norm"] == "comprar leche"
    assert row["final_area"] == "Personal"  # el nombre guardado del área, tal cual


def test_mostrar_un_area_guardada_en_minuscula_no_la_modifica(bot, conn, clock):
    old = legacy_area(conn, "viajes")
    tasks.create_task(conn, "reservar hotel", clock, area_id=old)
    text = fmt.plain(bot.reply("/pendientes"))
    assert "Viajes\n1. Reservar hotel" in text
    assert stored_area_name(conn, old) == "viajes"
    assert conn.execute("SELECT title FROM tasks").fetchone()["title"] == "reservar hotel"


# --- El render: tarjetas, avisos, listas, botones -----------------------------------------------


def test_los_botones_de_area_van_con_mayuscula(bot, conn):
    legacy_area(conn, "viajes")
    bot.say("comprar leche")
    bot.tap("Tarea")
    labels = bot.labels()
    assert labels == [
        "Universidad",
        "Proyectos",
        "Iglesia",
        "Personal",
        "Viajes",
        "Sin área",
        "Cancelar",
    ]


def test_la_tarjeta_de_pregunta_muestra_el_texto_y_el_tipo_con_mayuscula(bot):
    bot.say("comprar leche")
    assert fmt.plain(bot.question[0]) == "¿Qué es?\n\nComprar leche"
    bot.tap("Tarea")
    assert fmt.plain(bot.question[0]) == "¿En qué área va?\n\nComprar leche\n\nTipo: Tarea"
    bot.tap("Iglesia")
    assert fmt.plain(bot.channel.log[-1][1]) == "Tarea guardada\n\nComprar leche\n\nÁrea: Iglesia"


def test_cancelar_muestra_el_texto_con_mayuscula(bot):
    bot.say("comprar leche")
    bot.tap("Cancelar")
    assert (
        fmt.plain(bot.channel.log[-1][1])
        == "Cancelado\n\nComprar leche\n\nSigue en tu bandeja como tarea."
    )


def test_sin_terminar_muestra_el_texto_con_mayuscula(bot):
    bot.say("comprar leche")
    bot.say("otra cosa")
    assert fmt.plain(bot.edits()[0]).startswith("Sin terminar\n\nComprar leche")


def test_la_tarjeta_de_fecha_limite_muestra_titulo_y_area_con_mayuscula(bot):
    bot.say("/tarea entregar informe mañana 5 pm")
    bot.tap("Universidad")
    assert fmt.plain(bot.question[0]).startswith("¿Es la fecha límite?\n\nEntregar informe")
    assert "Área: Universidad" in fmt.plain(bot.question[0])


def test_la_tarjeta_de_recordatorio_guardado_y_deshacer(bot, conn):
    bot.say("recordar llamar a mamá mañana 8am")
    bot.tap("Personal")
    assert fmt.plain(bot.channel.log[-1][1]).startswith("Recordatorio guardado\n\nLlamar a mamá")
    bot.tap("Deshacer")
    assert fmt.plain(bot.channel.log[-1][1]) == (
        "Deshecho · Llamar a mamá · vuelve a tu bandeja como tarea"
    )


def test_el_aviso_de_recordatorio_va_con_mayuscula_en_texto_y_area():
    assert fmt.reminder_notice("llamar a mamá", "personal", False) == fmt.Html(
        "<b>Llamar a mamá</b>\n\nRecordatorio · Personal"
    )
    assert fmt.reminder_notice("llamar a mamá", None, True) == fmt.Html(
        "<b>Llamar a mamá</b>\n\nRecordatorio <i>(retrasado)</i>"
    )


def test_el_aviso_que_arma_el_motor_va_con_mayuscula():
    text = reminders.format_reminder_text("pagar luz", "personal", False)
    assert fmt.plain(text) == "Pagar luz\n\nRecordatorio · Personal"


def test_hecho_y_pospuesto_muestran_el_texto_con_mayuscula(bot, conn, clock):
    reminder = add_reminder(conn, clock, "pagar luz", "2026-10-03 18:00")
    with conn:
        conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder.id,))
    ids = {c.label: c.id for c in reminders.reminder_choices(reminder.id)}
    bot.press(ids["+10 min"])
    assert fmt.plain(bot.channel.log[-1][1]).startswith("Pospuesto · Pagar luz · ")
    bot.press(ids["Hecho"])
    assert fmt.plain(bot.channel.log[-1][1]) == "Hecho · Pagar luz"


def test_pendientes_muestra_titulos_y_areas_con_mayuscula(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-05 17:00", "universidad")
    add_task(conn, clock, "sin fecha")
    text = fmt.plain(bot.reply("/pendientes"))
    assert text == (
        "Pendientes (2)\n\nUniversidad\n1. Entregar informe · lun 5 oct, 5:00 pm\n\n"
        "Sin área\n2. Sin fecha"
    )


def test_pendientes_con_area_lleva_el_area_con_mayuscula_en_el_titulo(bot, conn, clock):
    add_task(conn, clock, "regar plantas", None, "personal")
    text = fmt.plain(bot.reply("/pendientes personal"))
    assert text == "Pendientes · Personal (1)\n\n1. Regar plantas"


def test_la_tarea_abierta_desde_la_lista_lleva_titulo_y_area_con_mayuscula(bot, conn, clock):
    add_task(conn, clock, "regar plantas", None, "personal")
    bot.say("/pendientes")
    bot.tap("1")
    assert (
        fmt.plain(bot.question[0]) == "Regar plantas\n\nÁrea: Personal\n\n¿Qué hago con esta tarea?"
    )
    bot.tap("Hecha")
    assert "Hecha · Regar plantas" in fmt.plain(bot.channel.log[-1][1])


def test_hoy_muestra_tareas_recordatorios_y_areas_con_mayuscula(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00", "personal")
    assert fmt.plain(bot.reply("/hoy")) == (
        "Hoy · sábado 3 de octubre\n\n"
        "Tareas\nUniversidad\n- Entregar informe · hoy, 5:00 pm\n\n"
        "Recordatorios\n- hoy, 6:00 pm · Llamar a mamá · Personal"
    )


def test_recordatorios_muestra_texto_y_area_con_mayuscula(bot, conn, clock):
    add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00", "personal")
    text = fmt.plain(bot.reply("/recordatorios"))
    assert "- hoy, 6:00 pm · Llamar a mamá · Personal" in text


def test_areas_lista_los_nombres_con_mayuscula(bot, conn):
    legacy_area(conn, "viajes")
    text = fmt.plain(bot.reply("/areas"))
    assert text == (
        "Áreas (5)\n\n- Universidad\n- Proyectos\n- Iglesia\n- Personal\n- Viajes · sin descripción"
    )


def test_nombres_con_simbolos_se_escapan_y_se_capitalizan(bot, conn, clock):
    created = areas.create_area(conn, "r&d <x>", "", clock)
    add_task(conn, clock, "<b>probar</b> & medir", None, "r&d <x>")
    html = bot.reply("/pendientes")
    assert "1. <b>probar</b>" not in html
    assert "<b>R&amp;d &lt;x&gt;</b>\n1. &lt;b&gt;probar&lt;/b&gt; &amp; medir" in html
    assert created.name == "R&d <x>"


# --- Con la librería REAL (Update.de_json) -------------------------------------------------------


def test_real_los_botones_de_area_y_la_tarjeta_salen_con_mayuscula(conn, monkeypatch):
    real = RealPath(conn, monkeypatch)
    real.say("comprar leche")
    first = real.sends[-1]
    assert "Comprar leche" in first["text"] and "comprar leche" not in first["text"]
    kind_button = _button(first, "Tarea")
    real.press(kind_button["callback_data"])
    area_edit = real.edits[-1]
    labels = [b["text"] for row in _keyboard(area_edit) for b in row]
    assert labels == ["Universidad", "Proyectos", "Iglesia", "Personal", "Sin área", "Cancelar"]
    real.press(_button(area_edit, "Iglesia")["callback_data"])
    assert "Área: Iglesia" in real.edits[-1]["text"]
    assert "<b>Tarea guardada</b>" in real.edits[-1]["text"]


def test_real_pendientes_con_el_boton_de_un_numero(conn, clock, monkeypatch):
    add_task(conn, clock, "regar plantas", None, "personal")
    real = RealPath(conn, monkeypatch)
    real.say("/pendientes personal")
    sent = real.sends[-1]
    assert "<b>Pendientes · Personal (1)</b>" in sent["text"]
    real.press(_button(sent, "1")["callback_data"])
    assert real.edits[-1]["text"].startswith("<b>Regar plantas</b>")
    assert "Área: Personal" in real.edits[-1]["text"]


def test_real_nuevaarea_pregunta_con_el_nombre_en_mayuscula(conn, monkeypatch):
    real = RealPath(conn, monkeypatch)
    real.say("/nuevaarea salud")
    assert "¿Qué cubre «Salud»?" in real.sends[-1]["text"]


def _keyboard(call: dict) -> list[list[dict]]:
    markup = call["reply_markup"]
    return [[button.to_dict() for button in row] for row in markup.inline_keyboard]


def _button(call: dict, label: str) -> dict:
    [found] = [b for row in _keyboard(call) for b in row if b["text"] == label]
    return found


# --- Mutaciones: la capitalización se aplica al mostrar, nunca a lo guardado ----------------------


def test_ninguna_ruta_de_captura_toca_lo_guardado(bot, conn):
    bot.say("comprar leche")
    bot.tap("Nota")
    bot.tap("Personal")
    bot.say("/tarea pagar luz mañana 5 pm")
    bot.tap("Personal")
    bot.tap("Sí")
    rows = conn.execute("SELECT title, source_text FROM tasks ORDER BY id").fetchall()
    assert [r["source_text"] for r in rows] == ["comprar leche", "pagar luz mañana 5 pm"]
    assert rows[1]["title"] == "pagar luz"
    assert [n.text for n in notes.list_notes(conn)] == ["comprar leche"]


def test_la_descripcion_escrita_en_el_flujo_se_guarda_y_se_muestra_tal_cual(bot, conn):
    bot.say("/nuevaarea salud")
    bot.say("médico y gimnasio")
    created = areas.find_area_by_name(conn, "salud")
    assert created.description == "médico y gimnasio"
    assert fmt.plain(bot.channel.log[-1][1]) == "Área guardada\n\nSalud\n\nmédico y gimnasio"


def test_la_etiqueta_guarda_el_nombre_del_area_aunque_este_en_minuscula(bot, conn):
    legacy_area(conn, "viajes")
    bot.say("reservar hotel")
    bot.tap("Tarea")
    bot.tap("Viajes")
    [row] = conn.execute("SELECT text_norm, final_area FROM classification_log").fetchall()
    assert (row["text_norm"], row["final_area"]) == ("reservar hotel", "viajes")
    assert fmt.plain(bot.channel.log[-1][1]).endswith("Área: Viajes")


def test_la_etiqueta_de_un_recordatorio_guarda_el_area_en_minuscula_tal_cual(bot, conn):
    legacy_area(conn, "viajes")
    bot.say("recordar reservar hotel mañana 8am")
    bot.tap("Viajes")
    [row] = conn.execute("SELECT final_kind, final_area FROM classification_log").fetchall()
    assert (row["final_kind"], row["final_area"]) == ("reminder", "viajes")
    assert "Área: Viajes" in fmt.plain(bot.channel.log[-1][1])


def test_la_etiqueta_de_una_nota_guarda_el_area_en_minuscula_tal_cual(bot, conn):
    legacy_area(conn, "viajes")
    bot.say("/nota llevar pasaporte")
    bot.tap("Viajes")
    [row] = conn.execute("SELECT final_kind, final_area FROM classification_log").fetchall()
    assert (row["final_kind"], row["final_area"]) == ("note", "viajes")


def test_hoy_con_un_area_guardada_en_minuscula_la_muestra_con_mayuscula(bot, conn, clock):
    old = legacy_area(conn, "viajes")
    tasks.create_task(conn, "reservar hotel", clock, area_id=old)
    with conn:
        conn.execute("UPDATE tasks SET due_at_utc = '2026-10-03T23:00:00+00:00'")
    reminders.create_reminder(
        conn, "llamar a la aerolínea", clock() + timedelta(hours=1), clock, area_id=old
    )
    assert fmt.plain(bot.reply("/hoy")) == (
        "Hoy · sábado 3 de octubre\n\n"
        "Tareas\nViajes\n- Reservar hotel · hoy, 5:00 pm\n\n"
        "Recordatorios\n- hoy, 4:30 pm · Llamar a la aerolínea · Viajes"
    )
    assert fmt.plain(bot.reply("/hoy viajes")).startswith("Hoy · sábado 3 de octubre · Viajes\n")


def test_pendientes_con_un_area_guardada_en_minuscula_la_pone_con_mayuscula_en_el_titulo(
    bot, conn, clock
):
    old = legacy_area(conn, "viajes")
    tasks.create_task(conn, "reservar hotel", clock, area_id=old)
    assert (
        fmt.plain(bot.reply("/pendientes VIAJES")) == "Pendientes · Viajes (1)\n\n1. Reservar hotel"
    )
    bot.tap("1")
    assert "Área: Viajes" in fmt.plain(bot.question[0])


def test_recordatorios_con_un_area_guardada_en_minuscula_la_muestra_con_mayuscula(bot, conn, clock):
    old = legacy_area(conn, "viajes")
    reminders.create_reminder(
        conn, "llamar a la aerolínea", clock() + timedelta(hours=1), clock, area_id=old
    )
    assert "- hoy, 4:30 pm · Llamar a la aerolínea · Viajes" in fmt.plain(
        bot.reply("/recordatorios")
    )


def test_areas_con_solo_un_area_en_minuscula_la_lista_con_mayuscula(bot, conn):
    with conn:
        conn.execute("UPDATE areas SET archived = 1")
    legacy_area(conn, "viajes")
    assert fmt.plain(bot.reply("/areas")) == "Áreas (1)\n\n- Viajes · sin descripción"


# --- La regla real de cap_first está documentada y probada con sus casos ---------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("iOS", "iOS"),
        ("eBay", "eBay"),
        ("iPhone", "iPhone"),
        ("UNAM", "UNAM"),
        ("Ya", "Ya"),
        ("ya", "Ya"),
        ("iphone", "Iphone"),
        ("ebay vende", "Ebay vende"),
        ("iOS nuevo", "iOS nuevo"),
        ("compré un iPhone", "Compré un iPhone"),
        ("¿iOS o Android?", "¿iOS o Android?"),
    ],
)
def test_cap_first_respeta_una_primera_palabra_con_otra_mayuscula(text, expected):
    assert fmt.cap_first(text) == expected


def test_estilo_documenta_la_regla_real_de_cap_first():
    from pathlib import Path

    estilo = (Path(__file__).resolve().parent.parent / "docs" / "ESTILO.md").read_text(
        encoding="utf-8"
    )
    assert len(estilo.splitlines()) <= 25
    for expected in ("cap_first", "iOS", "eBay", "iPhone", "UNAM", "Ya", "otra mayúscula"):
        assert expected in estilo, expected
