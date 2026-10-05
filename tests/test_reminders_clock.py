"""M9: el motor relee el reloj en cada envío (un canal lento no debe falsear las horas).

Se simula un canal lento adelantando el reloj DENTRO del envío del primer recordatorio.
Reloj inicial: sábado 2026-10-03 15:30 en México (21:30 UTC). Silencio: 22:00-07:00.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from asistente.channels.base import TransientChannelError
from asistente.core import reminders
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import local_to_utc, to_utc_iso
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"
USER = "42"


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


@pytest.fixture
def channel() -> ScriptedChannel:
    return ScriptedChannel()


@pytest.fixture
def engine(conn, channel, clock) -> ReminderEngine:
    return ReminderEngine(conn, channel, USER, TZ, clock)


def tick(engine: ReminderEngine) -> int:
    return asyncio.run(engine.tick())


def row(conn, reminder_id: int):
    return reminders.get_reminder(conn, reminder_id)


def slow_first_send(channel: ScriptedChannel, clock, **delta: float) -> None:
    """El primer envío tarda `delta` (el reloj avanza mientras se envía); los demás, nada."""
    calls = []

    def hook() -> None:
        if not calls:
            clock.advance(**delta)
        calls.append(1)

    channel.during_send = hook


def test_last_fired_at_es_la_hora_en_que_termino_el_envio(conn, clock, engine, channel):
    first = reminders.create_reminder(conn, "a", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    start = clock()
    slow_first_send(channel, clock, minutes=3)
    tick(engine)
    assert row(conn, first.id).last_fired_at == to_utc_iso(start + timedelta(minutes=3))


def test_el_retrasado_se_calcula_con_la_hora_de_cada_envio(conn, clock, engine, channel):
    reminders.create_reminder(conn, "a", clock() + timedelta(minutes=1), clock)
    second = reminders.create_reminder(conn, "b", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    slow_first_send(channel, clock, minutes=3)  # b sale 3 min después de su hora
    assert tick(engine) == 2
    texts = [text for _, text, _, _ in channel.choices]
    assert texts == ["<b>A</b>\n\nRecordatorio", "<b>B</b>\n\nRecordatorio <i>(retrasado)</i>"]
    assert row(conn, second.id).last_fired_at == to_utc_iso(clock())


def test_el_silencio_se_reevalua_en_cada_envio(conn, clock, engine, channel):
    clock.current = local("2026-10-03 21:00")
    first = reminders.create_reminder(conn, "a", local("2026-10-03 21:58"), clock)
    second = reminders.create_reminder(conn, "b", local("2026-10-03 21:58"), clock)
    clock.current = local("2026-10-03 21:59")
    slow_first_send(channel, clock, minutes=2)  # termina a las 22:01, ya en silencio

    assert tick(engine) == 1
    assert row(conn, first.id).status == "sent"
    assert row(conn, second.id).status == "pending"  # retenido por el silencio

    clock.current = local("2026-10-04 07:00")
    assert tick(engine) == 1
    assert [text for _, text, _, _ in channel.choices][
        -1
    ] == "<b>B</b>\n\nRecordatorio <i>(retrasado)</i>"


def test_la_espera_tras_un_fallo_cuenta_desde_el_momento_del_fallo(conn, clock, engine, channel):
    reminders.create_reminder(conn, "a", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    start = clock()
    channel.always_fail_with(TransientChannelError("timeout"))
    slow_first_send(channel, clock, seconds=40)  # el envío tarda 40 s y luego falla
    tick(engine)
    assert len(channel.attempts) == 1

    clock.current = start + timedelta(seconds=65)  # 25 s después del fallo: aún espera (30 s)
    tick(engine)
    assert len(channel.attempts) == 1
    clock.current = start + timedelta(seconds=70)
    tick(engine)
    assert len(channel.attempts) == 2


def test_la_siguiente_de_la_serie_se_cuenta_desde_la_hora_programada(conn, clock, engine, channel):
    start = clock() + timedelta(minutes=1)
    reminders.create_reminder(conn, "serie", start, clock, rrule="FREQ=DAILY")
    clock.advance(minutes=1)
    slow_first_send(channel, clock, minutes=3)
    tick(engine)
    following = [r for r in reminders.list_pending(conn)][0]
    assert following.fire_at_utc == to_utc_iso(start + timedelta(days=1))  # sin deriva
