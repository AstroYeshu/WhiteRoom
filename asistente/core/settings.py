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


def get_meridiem_ask_range(conn: sqlite3.Connection) -> tuple[int, int]:
    """El ajuste `meridiem_ask_range` (p. ej. "5-11") como (bajo, alto)."""
    raw = get_setting(conn, "meridiem_ask_range")
    try:
        low_text, high_text = raw.split("-")
        low, high = int(low_text), int(high_text)
    except ValueError:
        raise ValueError(
            f"meridiem_ask_range inválido: «{raw}» (se espera algo como 5-11)"
        ) from None
    if not 1 <= low <= high <= 11:
        raise ValueError(f"meridiem_ask_range fuera de rango: «{raw}» (1 <= bajo <= alto <= 11)")
    return low, high
