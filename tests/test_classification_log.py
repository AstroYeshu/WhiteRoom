"""Etiquetas para la Fase 2, SIN IA: al completarse una tarjeta de captura se registra en
`classification_log` lo que decidió el dueño (source='user'). El texto va solo a la base.
"""

import logging

import pytest

from asistente.core import classification
from tests.botkit import Bot, module_loop  # noqa: F401


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def rows(conn) -> list[dict]:
    cursor = conn.execute("SELECT * FROM classification_log ORDER BY id")
    return [dict(row) for row in cursor]


# --- Normalizar ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("comprar pan", "comprar pan"),
        ("  Comprar   LECHE  ", "comprar leche"),
        ("Llamar a MAMÁ", "llamar a mama"),
        ("pagar luz 2 veces el 15", "pagar luz veces el"),
        ("Ñandú\ty\ncafé", "nandu y cafe"),
        ("", ""),
        ("123 456", ""),
    ],
)
def test_normalize_text(text, expected):
    assert classification.normalize_text(text) == expected


# --- Qué se registra -----------------------------------------------------------------------------


def test_una_tarea_con_area(bot, conn, clock):
    bot.say("/tarea Comprar PAN")
    assert rows(conn) == []  # nada hasta que la tarjeta se completa
    bot.tap("personal")
    [row] = rows(conn)
    assert row["source"] == "user"
    assert row["text_norm"] == "comprar pan"
    assert (row["final_kind"], row["final_area"]) == ("task", "personal")
    assert row["user_corrected"] == 0
    assert row["ts_utc"] == clock.current.isoformat(timespec="seconds")
    for column in ("pred_kind", "pred_kind_conf", "pred_area", "pred_area_conf", "latency_ms"):
        assert row[column] is None


def test_una_tarea_sin_area_guarda_area_nula(bot, conn):
    bot.say("/tarea sacar la basura")
    bot.tap("Sin área")
    [row] = rows(conn)
    assert row["final_kind"] == "task" and row["final_area"] is None


def test_un_mensaje_libre_donde_el_dueno_elige_nota(bot, conn):
    bot.say("la clave del wifi es azul")
    bot.tap("Nota")
    assert rows(conn) == []
    bot.tap("personal")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"], row["user_corrected"]) == ("note", "personal", 0)
    assert row["text_norm"] == "la clave del wifi es azul"


def test_un_mensaje_libre_donde_el_dueno_elige_tarea(bot, conn):
    bot.say("estudiar calculo")
    bot.tap("Tarea")
    bot.tap("universidad")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"], row["user_corrected"]) == (
        "task",
        "universidad",
        0,
    )


def test_un_recordatorio_se_registra_al_guardar_con_el_titulo_sin_fecha_ni_numeros(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea de calculo")
    bot.tap("universidad")
    assert rows(conn) == []  # falta confirmar
    bot.tap("Guardar")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"], row["user_corrected"]) == (
        "reminder",
        "universidad",
        0,
    )
    assert row["text_norm"] == "llevar tarea de calculo"
    assert not any(ch.isdigit() for ch in row["text_norm"])


def test_un_recordatorio_con_pregunta_de_fecha_se_registra_al_crearse(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("iglesia")
    assert rows(conn) == []
    bot.tap("Mañana")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"]) == ("reminder", "iglesia")
    assert row["text_norm"] == "llamar al dentista"


def test_una_tarea_con_fecha_limite_aceptada_registra_el_titulo_limpio(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    bot.tap("universidad")
    assert rows(conn) == []
    bot.tap("Sí")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"]) == ("task", "universidad")
    assert "viernes" not in row["text_norm"] and "entregar informe" in row["text_norm"]


def test_una_tarea_con_fecha_limite_rechazada_registra_el_texto_completo(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    bot.tap("universidad")
    bot.tap("No")
    [row] = rows(conn)
    assert row["final_kind"] == "task"
    assert row["text_norm"] == "entregar informe el viernes"


# --- user_corrected ------------------------------------------------------------------------------


def test_mejor_como_tarea_tras_recordatorio_es_una_correccion(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("iglesia")
    bot.tap("Mejor como tarea")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"], row["user_corrected"]) == ("task", "iglesia", 1)


def test_un_recordatorio_detectado_por_el_verbo_y_cambiado_a_tarea_es_correccion(bot, conn):
    bot.say("recordar llamar a mamá")  # el verbo ya dice qué es: no se pregunta el tipo
    bot.tap("personal")
    bot.tap("Mejor como tarea")
    [row] = rows(conn)
    assert (row["final_kind"], row["user_corrected"]) == ("task", 1)


def test_cambiar_y_volver_a_guardar_un_recordatorio_no_es_correccion(bot, conn):
    bot.say("recordar llamar a mamá mañana 8am")
    bot.tap("personal")
    [first] = rows(conn)
    assert first["user_corrected"] == 0
    bot.tap("Cambiar")
    bot.tap("Hoy")
    second = rows(conn)[-1]
    assert (second["final_kind"], second["user_corrected"]) == ("reminder", 0)
    assert len(rows(conn)) == 2


def test_cambiar_y_terminar_como_tarea_es_correccion(bot, conn):
    bot.say("recordar llamar a mamá mañana 8am")
    bot.tap("personal")
    bot.tap("Cambiar")
    bot.tap("Mejor como tarea")
    last = rows(conn)[-1]
    assert (last["final_kind"], last["user_corrected"]) == ("task", 1)


# --- Cuándo NO se registra ------------------------------------------------------------------------


def test_cancelar_no_registra_nada(bot, conn):
    bot.say("comprar leche")
    bot.tap("Cancelar")
    assert rows(conn) == []


def test_una_captura_abandonada_no_registra_nada(bot, conn):
    bot.say("comprar leche")
    bot.tap("Tarea")
    bot.say("otra cosa")  # descarta la tarjeta anterior
    assert rows(conn) == []


def test_deshacer_no_registra_una_fila_nueva(bot, conn):
    bot.say("recordar llamar a mamá mañana 8am")
    bot.tap("personal")
    before = len(rows(conn))
    bot.tap("Deshacer")
    assert len(rows(conn)) == before


def test_nuevaarea_no_registra_nada(bot, conn):
    bot.say("/nuevaarea Deportes")
    bot.tap("Omitir")
    assert rows(conn) == []


def test_un_extrano_no_registra_nada(bot, conn):
    bot.say("/tarea comprar pan", user=99999)
    assert rows(conn) == []


def test_la_doble_pulsacion_no_duplica_la_fila(bot, conn):
    bot.say("/tarea comprar pan")
    button = bot.choice_id("personal")
    bot.press(button)
    bot.press(button)
    assert len(rows(conn)) == 1


# --- Privacidad y resistencia ---------------------------------------------------------------------


def test_el_texto_solo_va_a_la_base_nunca_al_log(bot, conn, caplog):
    secret = "secretoultraprivado"
    with caplog.at_level(logging.DEBUG):
        bot.say(f"/tarea {secret} uno")
        bot.tap("personal")
        bot.say(f"{secret} dos")
        bot.tap("Nota")
        bot.tap("personal")
    assert secret not in caplog.text
    assert [row["text_norm"] for row in rows(conn)] == [f"{secret} uno", f"{secret} dos"]


def test_si_no_se_puede_registrar_la_captura_igual_se_completa(bot, conn, caplog):
    conn.execute("DROP TABLE classification_log")
    with caplog.at_level(logging.WARNING):
        bot.say("/tarea comprar pan")
        bot.tap("personal")
    [(title, area)] = conn.execute("SELECT title, area_id FROM tasks").fetchall()
    assert title == "comprar pan" and area is not None
    assert "comprar pan" not in caplog.text
    assert any("etiqueta" in r.getMessage() for r in caplog.records)


# --- Segundos asesinos de mutaciones ---------------------------------------------------------


def test_log_user_decision_guarda_cada_campo(conn, clock):
    classification.log_user_decision(conn, clock, "Llamar A  MAMÁ 2", "reminder", "personal", True)
    classification.log_user_decision(conn, clock, "x", "note", None, False)
    first, second = rows(conn)
    assert (first["source"], first["text_norm"], first["final_kind"]) == (
        "user",
        "llamar a mama",
        "reminder",
    )
    assert (first["final_area"], first["user_corrected"]) == ("personal", 1)
    assert (second["source"], second["final_area"], second["user_corrected"]) == ("user", None, 0)


def test_set_kind_recuerda_el_primer_tipo():
    from datetime import datetime

    from asistente.bot import inbox
    from asistente.bot.conversation import Flow

    flow = Flow(1, 1, "x", datetime(2026, 1, 1))
    inbox._set_kind(flow, inbox.KIND_REMINDER)
    inbox._set_kind(flow, inbox.KIND_TASK)
    assert (flow.kind, flow.first_kind) == (inbox.KIND_TASK, inbox.KIND_REMINDER)


def test_set_kind_no_pisa_el_primer_tipo():
    from datetime import datetime

    from asistente.bot import inbox
    from asistente.bot.conversation import Flow

    flow = Flow(1, 1, "x", datetime(2026, 1, 1))
    for kind in (inbox.KIND_NOTE, inbox.KIND_REMINDER, inbox.KIND_TASK):
        inbox._set_kind(flow, kind)
    assert flow.first_kind == inbox.KIND_NOTE


def test_fecha_limite_aceptada_sin_area(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    bot.tap("Sin área")
    bot.tap("Sí")
    [row] = rows(conn)
    assert (row["final_kind"], row["final_area"], row["user_corrected"]) == ("task", None, 0)
    assert "entregar informe" in row["text_norm"]


def test_recordar_con_comando_y_mejor_como_tarea_es_correccion(bot, conn):
    bot.say("/recordar llamar al dentista")
    bot.tap("iglesia")
    bot.tap("Mejor como tarea")
    [row] = rows(conn)
    assert (row["final_kind"], row["user_corrected"]) == ("task", 1)


def test_cambiar_tras_guardar_con_vista_previa_y_terminar_como_tarea(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea")
    bot.tap("universidad")
    bot.tap("Guardar")
    bot.tap("Cambiar")
    bot.tap("Mejor como tarea")
    kinds = [(row["final_kind"], row["user_corrected"]) for row in rows(conn)]
    assert kinds == [("reminder", 0), ("task", 1)]


@pytest.mark.parametrize("path", ["nota", "recordatorio"])
def test_si_falla_el_registro_la_nota_y_el_recordatorio_igual_se_guardan(bot, conn, caplog, path):
    secret = "secretoultraprivado"
    conn.execute("DROP TABLE classification_log")
    with caplog.at_level(logging.WARNING):
        if path == "nota":
            bot.say(f"{secret} nota")
            bot.tap("Nota")
            bot.tap("personal")
            assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 1
        else:
            bot.say(f"/recordar mañana 8am {secret}")
            bot.tap("personal")
            bot.tap("Guardar")
            assert conn.execute("SELECT count(*) FROM reminders").fetchone()[0] == 1
    assert secret not in caplog.text
    assert any("etiqueta" in r.getMessage() for r in caplog.records)
