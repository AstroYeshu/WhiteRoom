"""Tareas. Nada se borra: cerrar una tarea cambia su `status` (soft delete)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from asistente.timeutil import Clock, to_utc_iso


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    area_id: int | None
    due_at_utc: str | None
    status: str
    postponed_until_utc: str | None
    source_text: str | None
    created_at: str
    updated_at: str
    closed_at: str | None


def _from_row(row: sqlite3.Row) -> Task:
    return Task(**{key: row[key] for key in row.keys()})  # noqa: SIM118 (sqlite3.Row)


def get_task(conn: sqlite3.Connection, task_id: int) -> Task | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _from_row(row) if row else None


def create_task(
    conn: sqlite3.Connection,
    title: str,
    now: Clock,
    area_id: int | None = None,
    due_at_utc: datetime | None = None,
    source_text: str | None = None,
) -> Task:
    """Crea una tarea abierta. Sin `area_id` queda "sin área" (bandeja)."""
    stamp = to_utc_iso(now())
    with conn:
        cursor = conn.execute(
            "INSERT INTO tasks (title, area_id, due_at_utc, source_text, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                title,
                area_id,
                to_utc_iso(due_at_utc) if due_at_utc else None,
                source_text,
                stamp,
                stamp,
            ),
        )
    task = get_task(conn, cursor.lastrowid)
    assert task is not None
    return task


def set_area(conn: sqlite3.Connection, task_id: int, area_id: int | None, now: Clock) -> None:
    with conn:
        conn.execute(
            "UPDATE tasks SET area_id = ?, updated_at = ? WHERE id = ?",
            (area_id, to_utc_iso(now()), task_id),
        )


def set_due(
    conn: sqlite3.Connection, task_id: int, due_at_utc: datetime | None, now: Clock
) -> None:
    with conn:
        conn.execute(
            "UPDATE tasks SET due_at_utc = ?, updated_at = ? WHERE id = ?",
            (to_utc_iso(due_at_utc) if due_at_utc else None, to_utc_iso(now()), task_id),
        )


def _close(conn: sqlite3.Connection, task_id: int, status: str, now: Clock) -> bool:
    """Cierra una tarea abierta o pospuesta. Devuelve False si no existía o ya estaba cerrada."""
    stamp = to_utc_iso(now())
    with conn:
        cursor = conn.execute(
            "UPDATE tasks SET status = ?, closed_at = ?, updated_at = ?"
            " WHERE id = ? AND status IN ('open', 'postponed')",
            (status, stamp, stamp, task_id),
        )
    return cursor.rowcount == 1


def mark_done(conn: sqlite3.Connection, task_id: int, now: Clock) -> bool:
    return _close(conn, task_id, "done", now)


def drop_task(conn: sqlite3.Connection, task_id: int, now: Clock) -> bool:
    """Descartar = soft delete (`status='dropped'`); sigue en la base."""
    return _close(conn, task_id, "dropped", now)


def postpone_task(conn: sqlite3.Connection, task_id: int, until_utc: datetime, now: Clock) -> bool:
    stamp = to_utc_iso(now())
    with conn:
        cursor = conn.execute(
            "UPDATE tasks SET status = 'postponed', postponed_until_utc = ?, updated_at = ?"
            " WHERE id = ? AND status IN ('open', 'postponed')",
            (to_utc_iso(until_utc), stamp, task_id),
        )
    return cursor.rowcount == 1


def list_open(conn: sqlite3.Connection, area_id: int | None = None, limit: int = 50) -> list[Task]:
    """Tareas abiertas: primero las que tienen fecha (la más cercana antes), luego las demás."""
    sql = "SELECT * FROM tasks WHERE status = 'open'"
    params: list[object] = []
    if area_id is not None:
        sql += " AND area_id = ?"
        params.append(area_id)
    sql += " ORDER BY due_at_utc IS NULL, due_at_utc, id LIMIT ?"
    params.append(limit)
    return [_from_row(row) for row in conn.execute(sql, params)]


def list_due_before(
    conn: sqlite3.Connection, before_utc: datetime, area_id: int | None = None
) -> list[Task]:
    """Tareas abiertas con fecha anterior a `before_utc` (vencidas y de hoy, según el límite)."""
    sql = "SELECT * FROM tasks WHERE status = 'open' AND due_at_utc IS NOT NULL AND due_at_utc < ?"
    params: list[object] = [to_utc_iso(before_utc)]
    if area_id is not None:
        sql += " AND area_id = ?"
        params.append(area_id)
    sql += " ORDER BY due_at_utc, id"
    return [_from_row(row) for row in conn.execute(sql, params)]
