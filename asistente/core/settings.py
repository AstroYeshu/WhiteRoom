"""Lectura de la tabla `settings` (clave/valor de texto)."""

from __future__ import annotations

import sqlite3
from datetime import time

from asistente.timeutil import parse_hhmm


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise KeyError(f"Falta el ajuste «{key}» en la tabla settings")
    return row["value"]


def get_time_setting(conn: sqlite3.Connection, key: str) -> time:
    """Un ajuste con formato `HH:MM` como `datetime.time`."""
    return parse_hhmm(get_setting(conn, key))
