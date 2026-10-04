"""M5: "🌅 Mañana" antes de las 05:00 locales ofrece HOY a la hora por defecto.

A las 02:30 "mañana" casi siempre significa "cuando me levante", o sea hoy. Zona: México.
"""

from datetime import datetime, timedelta

import pytest

from asistente.core import reminders
from asistente.timeutil import local_to_utc, to_utc_iso

TZ = "America/Mexico_City"


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


def sent_reminder(conn, clock) -> int:
    """Un recordatorio ya avisado (el botón 🌅 solo aplica a esos)."""
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    with conn:
        conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (created.id,))
    return created.id


def set_morning(conn, value: str) -> None:
    with conn:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'default_morning_time'", (value,))


@pytest.mark.parametrize(
    ("now_local", "expected_local"),
    [
        ("2026-10-05 00:00", "2026-10-05 09:00"),  # medianoche: hoy
        ("2026-10-05 02:30", "2026-10-05 09:00"),
        ("2026-10-05 04:59", "2026-10-05 09:00"),  # último minuto "de madrugada"
        ("2026-10-05 05:00", "2026-10-06 09:00"),  # desde las 05:00 es mañana de verdad
        ("2026-10-05 15:30", "2026-10-06 09:00"),
        ("2026-10-05 23:59", "2026-10-06 09:00"),
    ],
)
def test_manana_segun_la_hora_local(conn, clock, now_local, expected_local):
    clock.current = local(now_local)
    reminder_id = sent_reminder(conn, clock)
    target = reminders.snooze_until_tomorrow(conn, reminder_id, clock, TZ)
    assert target == local(expected_local)
    stored = reminders.get_reminder(conn, reminder_id)
    assert (stored.status, stored.fire_at_utc) == ("pending", to_utc_iso(local(expected_local)))


def test_si_la_hora_por_defecto_de_hoy_ya_paso_va_a_manana(conn, clock):
    set_morning(conn, "04:00")
    clock.current = local("2026-10-05 04:30")  # antes de las 05:00, pero las 04:00 ya pasaron
    reminder_id = sent_reminder(conn, clock)
    assert reminders.snooze_until_tomorrow(conn, reminder_id, clock, TZ) == local(
        "2026-10-06 04:00"
    )


def test_si_la_hora_por_defecto_de_hoy_aun_no_llega_va_a_hoy(conn, clock):
    set_morning(conn, "04:00")
    clock.current = local("2026-10-05 03:00")
    reminder_id = sent_reminder(conn, clock)
    assert reminders.snooze_until_tomorrow(conn, reminder_id, clock, TZ) == local(
        "2026-10-05 04:00"
    )


def test_la_hora_por_defecto_exactamente_ahora_va_a_manana(conn, clock):
    set_morning(conn, "03:00")
    clock.current = local("2026-10-05 03:00")  # nunca se programa en el pasado ni en este instante
    reminder_id = sent_reminder(conn, clock)
    assert reminders.snooze_until_tomorrow(conn, reminder_id, clock, TZ) == local(
        "2026-10-06 03:00"
    )
