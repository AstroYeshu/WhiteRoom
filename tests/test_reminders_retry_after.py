"""M1: el motor respeta la espera que pide el canal (RetryAfter), con un tope de 10 min."""

import asyncio
from datetime import timedelta

import pytest

from asistente.channels.base import TransientChannelError
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


def due_reminder(conn, clock):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    return created


def attempts_after(engine, channel, clock, seconds: int) -> int:
    clock.advance(seconds=seconds)
    tick(engine)
    return len(channel.attempts)


def test_espera_al_menos_lo_que_pide_telegram(conn, clock, engine, channel):
    due_reminder(conn, clock)
    channel.always_fail_with(TransientChannelError("rate_limited", retry_after=120))
    tick(engine)
    assert len(channel.attempts) == 1
    # El backoff normal sería de 30 s; Telegram pidió 120 s.
    assert attempts_after(engine, channel, clock, 119) == 1
    assert attempts_after(engine, channel, clock, 1) == 2


def test_si_el_backoff_propio_es_mayor_manda_el_backoff(conn, clock, engine, channel):
    due_reminder(conn, clock)
    channel.always_fail_with(TransientChannelError("rate_limited", retry_after=5))
    tick(engine)
    assert attempts_after(engine, channel, clock, 29) == 1
    assert attempts_after(engine, channel, clock, 1) == 2


def test_la_espera_pedida_tiene_tope_de_10_minutos(conn, clock, engine, channel):
    due_reminder(conn, clock)
    channel.always_fail_with(TransientChannelError("rate_limited", retry_after=86_400))
    tick(engine)
    assert attempts_after(engine, channel, clock, 599) == 1
    assert attempts_after(engine, channel, clock, 1) == 2


def test_retry_after_no_toca_la_hora_programada(conn, clock, engine, channel):
    created = due_reminder(conn, clock)
    before = reminders.get_reminder(conn, created.id).fire_at_utc
    channel.always_fail_with(TransientChannelError("rate_limited", retry_after=120))
    tick(engine)
    assert reminders.get_reminder(conn, created.id).fire_at_utc == before
