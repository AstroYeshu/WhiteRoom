"""Carreras entre el envío y el usuario (M2): algo cambia mientras el mensaje está saliendo.

Reloj inicial: sábado 2026-10-03 15:30 en México (21:30 UTC).
"""

import asyncio
from datetime import timedelta

import pytest

from asistente.core import reminders
from asistente.core.reminders import Delivery, ReminderEngine
from asistente.timeutil import to_utc_iso
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"
USER = "42"


@pytest.fixture
def channel() -> ScriptedChannel:
    return ScriptedChannel()


@pytest.fixture
def engine(conn, channel, clock) -> ReminderEngine:
    return ReminderEngine(conn, channel, USER, TZ, clock)


def tick(engine: ReminderEngine) -> int:
    return asyncio.run(engine.tick())


def all_rows(conn):
    return [
        reminders.get_reminder(conn, r["id"])
        for r in conn.execute("SELECT id FROM reminders ORDER BY id")
    ]


def test_cancelado_mientras_se_envia_no_marca_sent_ni_crea_siguiente(conn, clock, engine, channel):
    created = reminders.create_reminder(
        conn, "serie", clock() + timedelta(minutes=1), clock, rrule="FREQ=DAILY"
    )
    clock.advance(minutes=1)
    channel.during_send = lambda: reminders.cancel(conn, created.id)

    assert tick(engine) == 0  # no cuenta como registrado
    rows = all_rows(conn)
    assert len(rows) == 1  # sin siguiente de serie
    assert rows[0].status == "cancelled" and rows[0].last_fired_at is None


def test_cancelado_mientras_se_envia_no_insiste(conn, clock, engine, channel):
    created = reminders.create_reminder(
        conn, "urgente", clock() + timedelta(minutes=1), clock, priority=2
    )
    clock.advance(minutes=1)
    channel.during_send = lambda: reminders.cancel(conn, created.id)
    tick(engine)
    channel.during_send = None

    for _ in range(4):  # pasa de sobra el intervalo de insistencia
        clock.advance(minutes=15)
        assert tick(engine) == 0
    assert len(channel.attempts) == 1
    assert reminders.get_reminder(conn, created.id).nag_count == 0


def test_reprogramado_mientras_se_envia_no_se_pisa(conn, clock, engine, channel):
    created = reminders.create_reminder(
        conn, "serie", clock() + timedelta(minutes=1), clock, rrule="FREQ=DAILY"
    )
    clock.advance(minutes=1)
    later = clock() + timedelta(minutes=10)

    def reschedule() -> None:  # un posponer pulsado a mitad del envío
        with conn:
            conn.execute(
                "UPDATE reminders SET fire_at_utc = ? WHERE id = ?",
                (to_utc_iso(later), created.id),
            )

    channel.during_send = reschedule
    assert tick(engine) == 0
    channel.during_send = None

    stored = reminders.get_reminder(conn, created.id)
    assert (stored.status, stored.fire_at_utc, stored.last_fired_at) == (
        "pending",
        to_utc_iso(later),
        None,
    )
    assert len(all_rows(conn)) == 1  # sin siguiente

    clock.advance(minutes=10)  # a su nueva hora sale una vez y ahí sí genera la siguiente
    assert tick(engine) == 1
    assert [r.status for r in all_rows(conn)] == ["sent", "pending"]


def test_la_fila_cambiada_antes_de_enviar_no_se_envia(conn, clock, engine, channel):
    """Releer antes de enviar: si la fila ya no está pendiente en el tick, no sale nada."""
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    due = reminders.list_due(conn, clock())
    assert [r.id for r in due] == [created.id]
    reminders.cancel(conn, created.id)  # entre la consulta y el envío

    assert asyncio.run(engine._deliver(due[0])) is Delivery.SKIPPED
    assert channel.attempts == []
