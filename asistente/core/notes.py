"""Notas. Nada se borra: archivar es el soft delete."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from asistente.timeutil import Clock, to_utc_iso


@dataclass(frozen=True)
class Note:
    id: int
    text: str
    area_id: int | None
    created_at: str
    archived: bool


def _from_row(row: sqlite3.Row) -> Note:
    return Note(row["id"], row["text"], row["area_id"], row["created_at"], bool(row["archived"]))


def create_note(
    conn: sqlite3.Connection, text: str, now: Clock, area_id: int | None = None
) -> Note:
    with conn:
        cursor = conn.execute(
            "INSERT INTO notes (text, area_id, created_at) VALUES (?, ?, ?)",
            (text, area_id, to_utc_iso(now())),
        )
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _from_row(row)


def set_area(conn: sqlite3.Connection, note_id: int, area_id: int | None) -> None:
    with conn:
        conn.execute("UPDATE notes SET area_id = ? WHERE id = ?", (area_id, note_id))


def archive_note(conn: sqlite3.Connection, note_id: int) -> None:
    with conn:
        conn.execute("UPDATE notes SET archived = 1 WHERE id = ?", (note_id,))


def list_notes(conn: sqlite3.Connection, area_id: int | None = None, limit: int = 20) -> list[Note]:
    """Las notas no archivadas más recientes primero."""
    sql = "SELECT * FROM notes WHERE archived = 0"
    params: list[object] = []
    if area_id is not None:
        sql += " AND area_id = ?"
        params.append(area_id)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return [_from_row(row) for row in conn.execute(sql, params)]
