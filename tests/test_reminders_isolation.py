"""M1: un recordatorio que falla por culpa propia no bloquea a los demás.

- Culpa del mensaje (`PermanentChannelError`): se detiene esa fila; no hay corta-circuito.
- Excepción inesperada: pasajera, salvo que otros recordatorios SÍ salgan después en el mismo tick;
  entonces el canal está vivo y la culpa es de esa fila: se aísla y se detiene.
"""

import asyncio
from datetime import timedelta

import pytest

from asistente.channels.base import (
    PermanentChannelError,
    TransientChannelError,
    UnclassifiedChannelError,
)
from asistente.core import reminders
from asistente.core.reminders import ReminderEngine
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"


@pytest.fixture
def channel() -> ScriptedChannel:
    return ScriptedChannel()


@pytest.fixture
def engine(conn, channel, clock) -> ReminderEngine:
    return ReminderEngine(conn, channel, "42", TZ, clock)


def tick(engine: ReminderEngine) -> int:
    return asyncio.run(engine.tick())


def row(conn, reminder_id: int):
    return reminders.get_reminder(conn, reminder_id)


def make(conn, clock, *texts: str) -> list[int]:
    """Un recordatorio por texto, con horas crecientes (se envían en el orden de la lista)."""
    ids = [
        reminders.create_reminder(conn, text, clock() + timedelta(minutes=i), clock).id
        for i, text in enumerate(texts, start=1)
    ]
    clock.advance(minutes=len(texts))
    return ids


def fail_texts(channel: ScriptedChannel, error: Exception, *marks: str) -> None:
    channel.fail_if = lambda text: error if any(mark in text for mark in marks) else None


def sent_texts(channel: ScriptedChannel) -> list[str]:
    return [text for _, text, _, _ in channel.choices]


# --- Culpa del mensaje (permanente) -----------------------------------------------------------


def test_badrequest_con_dos_validos_en_el_mismo_tick_los_dos_validos_salen(
    conn, clock, engine, channel
):
    first, bad, last = make(conn, clock, "uno", "malo", "tres")
    fail_texts(channel, PermanentChannelError("bad_request:wrong_entity"), "Malo")
    assert tick(engine) == 2
    assert sent_texts(channel) == ["<b>Uno</b>\n\nRecordatorio", "<b>Tres</b>\n\nRecordatorio"]
    assert row(conn, first).status == row(conn, last).status == "sent"
    stopped = row(conn, bad)
    assert stopped.stopped and stopped.status == "pending"
    assert (
        conn.execute("SELECT stop_reason FROM reminders WHERE id = ?", (bad,)).fetchone()[0]
        == "permanent:bad_request:wrong_entity"
    )


def test_el_permanente_no_activa_la_espera_del_canal(conn, clock, engine, channel):
    (bad,) = make(conn, clock, "malo")
    fail_texts(channel, PermanentChannelError("bad_request:x"), "Malo")
    tick(engine)
    (good,) = make(conn, clock, "bueno")
    # Sin avanzar el reloj: si el canal estuviera en espera, "bueno" no saldría.
    assert tick(engine) == 1
    assert row(conn, good).status == "sent" and row(conn, bad).stopped


# --- Excepción inesperada ---------------------------------------------------------------------


def test_una_excepcion_inesperada_con_otros_que_salen_despues_se_aisla_y_se_detiene(
    conn, clock, engine, channel
):
    bad, good_a, good_b = make(conn, clock, "malo", "bueno-a", "bueno-b")
    fail_texts(channel, RuntimeError("raro"), "Malo")
    assert tick(engine) == 2
    assert sent_texts(channel) == [
        "<b>Bueno-a</b>\n\nRecordatorio",
        "<b>Bueno-b</b>\n\nRecordatorio",
    ]
    stopped = row(conn, bad)
    assert stopped.stopped and stopped.status == "pending"
    assert (
        conn.execute("SELECT stop_reason FROM reminders WHERE id = ?", (bad,)).fetchone()[0]
        == "permanent:unexpected:RuntimeError"
    )
    assert row(conn, good_a).status == row(conn, good_b).status == "sent"


def test_el_aislado_no_vuelve_a_intentarse_en_el_siguiente_tick(conn, clock, engine, channel):
    make(conn, clock, "malo", "bueno")
    fail_texts(channel, RuntimeError("raro"), "Malo")
    tick(engine)
    attempts = len(channel.attempts)
    clock.advance(hours=1)
    tick(engine)
    assert len(channel.attempts) == attempts


def test_una_excepcion_inesperada_tras_el_ultimo_envio_sigue_siendo_pasajera(
    conn, clock, engine, channel
):
    """Si nadie sale DESPUÉS del fallo, no se sabe si falló el canal o la fila: se reintenta."""
    good, bad = make(conn, clock, "bueno", "malo")
    fail_texts(channel, RuntimeError("raro"), "Malo")
    assert tick(engine) == 1
    stored = row(conn, bad)
    assert (stored.status, stored.attempts, stored.stopped) == ("pending", 1, False)
    assert row(conn, good).status == "sent"


def test_si_todos_fallan_con_excepcion_inesperada_es_una_sola_espera_de_canal(
    conn, clock, engine, channel
):
    first, second = make(conn, clock, "a", "b")
    channel.always_fail_with(RuntimeError("raro"))
    tick(engine)
    assert len(channel.attempts) == 2  # se probó con los dos antes de rendirse
    assert not row(conn, first).stopped and not row(conn, second).stopped
    assert (row(conn, first).attempts, row(conn, second).attempts) == (1, 1)
    clock.advance(seconds=29)
    tick(engine)
    assert len(channel.attempts) == 2  # espera de 30 s, no de 60 s
    clock.advance(seconds=1)
    tick(engine)
    assert len(channel.attempts) == 4


def test_tres_fallos_inesperados_seguidos_cortan_el_tick(conn, clock, engine, channel):
    ids = make(conn, clock, "a", "b", "c", "d", "e")
    channel.always_fail_with(RuntimeError("raro"))
    tick(engine)
    assert len(channel.attempts) == 3
    assert not any(row(conn, i).stopped for i in ids)


def test_tras_tres_fallos_seguidos_los_no_intentados_comparten_la_caida(
    conn, clock, engine, channel
):
    ids = make(conn, clock, "a", "b", "c", "d")
    channel.always_fail_with(RuntimeError("raro"))
    tick(engine)
    assert row(conn, ids[3]).first_failed_at is not None  # empieza su horizonte como en 8.3


def test_un_fallo_transitorio_declarado_corta_y_no_aisla_a_los_anteriores(
    conn, clock, engine, channel
):
    bad, down, never = make(conn, clock, "malo", "caido", "nunca")
    channel.fail_if = lambda text: (
        RuntimeError("raro")
        if "Malo" in text
        else TransientChannelError("telegram_down")
        if "Caido" in text
        else None
    )
    assert tick(engine) == 0
    assert len(channel.attempts) == 2  # "nunca" no se intentó: el canal está caído
    assert not row(conn, bad).stopped and row(conn, bad).attempts == 1
    assert not row(conn, down).stopped
    assert "<b>Nunca</b>\n\nRecordatorio" not in channel.attempts


def test_el_texto_del_usuario_nunca_va_al_log(conn, clock, engine, channel, caplog):
    make(conn, clock, "secreto-médico", "otro")
    fail_texts(channel, RuntimeError("secreto-médico"), "Secreto")
    with caplog.at_level("DEBUG"):
        tick(engine)
    assert "RuntimeError" in caplog.text
    assert "secreto-médico" not in caplog.text


# --- Error de Telegram sin categoría (Conflict y similares) -----------------------------------


def test_sin_categoria_con_otro_que_sale_despues_se_detiene_con_su_clase(
    conn, clock, engine, channel
):
    odd, good = make(conn, clock, "raro", "bueno")
    fail_texts(channel, UnclassifiedChannelError("telegram_error:Conflict"), "Raro")
    assert tick(engine) == 1
    stopped = row(conn, odd)
    assert stopped.stopped
    assert (
        conn.execute("SELECT stop_reason FROM reminders WHERE id = ?", (odd,)).fetchone()[0]
        == "permanent:telegram_error:Conflict"
    )
    assert row(conn, good).status == "sent"


def test_sin_categoria_y_nadie_sale_despues_es_transitorio(conn, clock, engine, channel):
    (odd,) = make(conn, clock, "raro")
    channel.always_fail_with(UnclassifiedChannelError("telegram_error:Conflict"))
    tick(engine)
    stored = row(conn, odd)
    assert (stored.status, stored.attempts, stored.stopped) == ("pending", 1, False)


# --- Anti-bloqueo: rotos al frente, válidos detrás --------------------------------------------

BROKEN_ERRORS = [
    RuntimeError("raro"),
    UnclassifiedChannelError("telegram_error:Conflict"),
]


@pytest.mark.parametrize("error", BROKEN_ERRORS, ids=["inesperado", "sin_categoria"])
def test_tres_rotos_al_frente_no_dejan_sin_salir_a_los_validos(conn, clock, engine, channel, error):
    ids = make(conn, clock, "roto-1", "roto-2", "roto-3", "bueno-a", "bueno-b")
    fail_texts(channel, error, "Roto")
    for _ in range(2):  # como máximo 2 ticks (el segundo, pasada la espera de 30 s)
        tick(engine)
        clock.advance(seconds=31)
    assert [r.status for r in map(lambda i: row(conn, i), ids[3:])] == ["sent", "sent"]
    assert all(row(conn, i).stopped for i in ids[:3])  # y los rotos quedaron aislados

    attempts = len(channel.attempts)
    tick(engine)
    clock.advance(seconds=31)
    tick(engine)
    assert len(channel.attempts) == attempts  # los rotos ya no se intentan en cada tick


@pytest.mark.parametrize("error", BROKEN_ERRORS, ids=["inesperado", "sin_categoria"])
def test_rotos_al_frente_no_bloquean_recordatorios_nuevos_en_cada_tick(
    conn, clock, engine, channel, error
):
    """Mientras los rotos siguen vivos (aún sin veredicto), un aviso nuevo y válido sale igual."""
    make(conn, clock, "roto-1", "roto-2", "roto-3")
    fail_texts(channel, error, "Roto")
    tick(engine)  # tres fallos seguidos: se corta el tick
    clock.advance(seconds=31)
    (new,) = make(conn, clock, "nuevo")
    tick(engine)
    assert row(conn, new).status == "sent"
