"""Tareas y sus avisos de preparación: M7 (tareas pospuestas) y M8 (una sola transacción).

Reloj inicial: sábado 2026-10-03 15:30 en México (21:30 UTC).
"""

import sqlite3
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


# --- M8: la tarea y sus avisos son UNA transacción --------------------------------------------


def fail_on_second_notice(conn) -> None:
    """Hace fallar de verdad el aviso de "1 hora antes" (el segundo que se inserta)."""
    conn.execute(
        "CREATE TEMP TRIGGER boom BEFORE INSERT ON reminders"
        " WHEN NEW.text LIKE 'En 1 hora vence%'"
        " BEGIN SELECT RAISE(ABORT, 'falla simulada'); END"
    )


def test_create_task_con_fallo_en_un_aviso_no_deja_nada_a_medias(conn, clock):
    fail_on_second_notice(conn)
    with pytest.raises(sqlite3.Error):
        tasks.create_task(conn, "entrega", clock, due_at_utc=clock() + timedelta(days=3))
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0  # ni el de 1 día


def test_set_due_con_fallo_conserva_la_fecha_y_los_avisos_anteriores(conn, clock):
    old_due = clock() + timedelta(days=3)
    task = tasks.create_task(conn, "entrega", clock, due_at_utc=old_due)
    before = sorted(r.id for r in alive(conn, task.id))
    assert len(before) == 2

    fail_on_second_notice(conn)
    with pytest.raises(sqlite3.Error):
        tasks.set_due(conn, task.id, clock() + timedelta(days=6), clock)

    assert tasks.get_task(conn, task.id).due_at_utc == to_utc_iso(old_due)
    assert sorted(r.id for r in alive(conn, task.id)) == before  # los viejos siguen vivos


@pytest.mark.parametrize(
    "action",
    [
        lambda conn, task, clock: tasks.drop_task(conn, task.id, clock),
        lambda conn, task, clock: tasks.mark_done(conn, task.id, clock),
        lambda conn, task, clock: tasks.postpone_task(
            conn, task.id, clock() + timedelta(days=1), clock
        ),
    ],
    ids=["descartar", "hacer", "posponer"],
)
def test_cerrar_o_posponer_y_cancelar_avisos_es_una_transaccion(conn, clock, action):
    task = tasks.create_task(conn, "x", clock, due_at_utc=clock() + timedelta(days=3))
    conn.execute(
        "CREATE TEMP TRIGGER boom BEFORE UPDATE ON reminders"
        " WHEN NEW.status = 'cancelled' BEGIN SELECT RAISE(ABORT, 'falla simulada'); END"
    )
    with pytest.raises(sqlite3.Error):
        action(conn, task, clock)
    assert tasks.get_task(conn, task.id).status == "open"  # la tarea no cambió a medias
    assert len(alive(conn, task.id)) == 2
