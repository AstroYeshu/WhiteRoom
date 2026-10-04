"""Tareas y sus avisos de preparación: M7 (tareas pospuestas) y M8 (una sola transacción).

Reloj inicial: sábado 2026-10-03 15:30 en México (21:30 UTC).
"""

from datetime import timedelta

import pytest

from asistente.core import reminders, tasks
from asistente.timeutil import to_utc_iso


def alive(conn, task_id: int) -> list[reminders.Reminder]:
    return [r for r in reminders.list_pending(conn) if r.task_id == task_id]


# --- M7: set_due también en tareas pospuestas -------------------------------------------------


def test_set_due_recrea_los_avisos_en_una_tarea_pospuesta(conn, clock):
    task = tasks.create_task(conn, "entrega", clock, due_at_utc=clock() + timedelta(days=3))
    assert len(alive(conn, task.id)) == 2
    assert tasks.postpone_task(conn, task.id, clock() + timedelta(days=1), clock)
    assert alive(conn, task.id) == []  # posponer cancela los avisos

    new_due = clock() + timedelta(days=5)
    tasks.set_due(conn, task.id, new_due, clock)

    assert tasks.get_task(conn, task.id).status == "postponed"  # sigue pospuesta
    fire_times = sorted(r.fire_at_utc for r in alive(conn, task.id))
    assert fire_times == [
        to_utc_iso(new_due - timedelta(days=1)),
        to_utc_iso(new_due - timedelta(hours=1)),
    ]


@pytest.mark.parametrize("close", [tasks.mark_done, tasks.drop_task])
def test_set_due_no_recrea_avisos_en_una_tarea_cerrada(conn, clock, close):
    task = tasks.create_task(conn, "x", clock, due_at_utc=clock() + timedelta(days=3))
    close(conn, task.id, clock)
    tasks.set_due(conn, task.id, clock() + timedelta(days=5), clock)
    assert alive(conn, task.id) == []
