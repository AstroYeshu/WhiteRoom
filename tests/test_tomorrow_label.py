"""Bloque 6, punto 3: la etiqueta "Mañana" pasa a "Hoy 9:00 am" antes de las 05:00 locales.

La etiqueta y la acción salen de la MISMA función, así que no pueden discrepar.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from asistente.core import reminders
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import from_utc_iso, local_to_utc, to_local
from tests.fakes import FakeChannel

TZ = "America/Mexico_City"


def at(hour: int, minute: int = 0) -> datetime:
    return local_to_utc(datetime(2026, 10, 4, hour, minute), TZ)


@pytest.mark.parametrize(
    ("hour", "minute", "label"),
    [
        (0, 0, "Hoy 9:00 am"),
        (3, 0, "Hoy 9:00 am"),
        (4, 59, "Hoy 9:00 am"),
        (5, 0, "Mañana 9:00 am"),  # 05:00 ya no cuenta como madrugada
        (15, 30, "Mañana 9:00 am"),
        (23, 59, "Mañana 9:00 am"),
    ],
)
def test_etiqueta_segun_la_hora_local(conn, hour, minute, label):
    assert reminders.tomorrow_label(conn, at(hour, minute), TZ) == label


def test_la_etiqueta_usa_la_hora_por_defecto_de_settings(conn):
    with conn:
        conn.execute("UPDATE settings SET value = '08:30' WHERE key = 'default_morning_time'")
    assert reminders.tomorrow_label(conn, at(3), TZ) == "Hoy 8:30 am"


def test_si_la_hora_por_defecto_de_hoy_ya_paso_la_etiqueta_es_manana(conn):
    with conn:
        conn.execute("UPDATE settings SET value = '04:00' WHERE key = 'default_morning_time'")
    assert reminders.tomorrow_label(conn, at(3), TZ) == "Hoy 4:00 am"
    assert reminders.tomorrow_label(conn, at(4, 30), TZ) == "Mañana 4:00 am"


@pytest.mark.parametrize("morning", ["09:00", "04:00", "07:45"])
def test_etiqueta_y_accion_nunca_discrepan(conn, clock, morning):
    """Para cada media hora del día: "Hoy" si y solo si la acción cae en el día local de hoy."""
    with conn:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'default_morning_time'", (morning,))
    for half_hours in range(48):
        moment = at(0) + timedelta(minutes=30 * half_hours)
        clock.current = moment
        created = reminders.create_reminder(conn, "x", moment + timedelta(hours=1), clock)
        with conn:
            conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (created.id,))
        target = reminders.snooze_until_tomorrow(conn, created.id, clock, TZ)
        label = reminders.tomorrow_label(conn, moment, TZ)
        same_day = to_local(target, TZ).date() == to_local(moment, TZ).date()
        assert label.startswith("Hoy") == same_day, (moment, label, target)


def test_el_motor_envia_los_botones_con_la_etiqueta_del_momento(conn, clock):
    """Prioridad 2 para saltarse el silencio (22:00-07:00): a las 03:00 hay que enviarlo."""
    clock.current = at(2, 59)
    reminders.create_reminder(conn, "x", at(3), clock, priority=2)
    clock.current = at(3)
    channel = FakeChannel()
    engine = ReminderEngine(conn, channel, "42", TZ, clock)
    assert asyncio.run(engine.tick()) == 1
    labels = [c.label for c in channel.choices[0][2]]
    assert labels == ["Hecho", "+10 min", "+1 h", "Hoy 9:00 am"]
    assert channel.choices[0][2][3].id.startswith("rem_tomorrow:")


def test_la_accion_de_manana_madrugada_coincide_con_la_hora_de_la_etiqueta(conn, clock):
    clock.current = at(3)
    created = reminders.create_reminder(conn, "x", at(3, 5), clock)
    with conn:
        conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (created.id,))
    reminders.snooze_until_tomorrow(conn, created.id, clock, TZ)
    stored = reminders.get_reminder(conn, created.id)
    assert from_utc_iso(stored.fire_at_utc) == at(9)
