"""Etiquetas para la Fase 2: lo que el dueño decidió, guardado en `classification_log`.

Hoy no hay clasificador ni IA: cada captura que el dueño completa deja una fila `source='user'`
con el texto normalizado y el tipo y área finales. Con ellas la Fase 2 podrá medir y aprender.
El texto va SOLO a la base, nunca al log.
"""

from __future__ import annotations

import re
import sqlite3

from asistente.parsing.dates import fold
from asistente.timeutil import Clock, to_utc_iso

_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, sin números y con los espacios colapsados (SPEC 8.2)."""
    return _SPACES.sub(" ", _DIGITS.sub(" ", fold(text))).strip()


def log_user_decision(
    conn: sqlite3.Connection,
    now: Clock,
    text: str,
    final_kind: str,
    final_area: str | None,
    user_corrected: bool,
    capture_id: int | None = None,
) -> None:
    """Una fila `source='user'`. `final_kind`: task, reminder o note; `final_area`: el nombre del
    área o None si quedó sin área. Los campos de predicción quedan vacíos (no hubo clasificador).

    `capture_id` es la tarea de bandeja de la captura: UNA fila por captura. Decidir otra vez la
    misma captura («Cambiar») ACTUALIZA su fila y la deja con `user_corrected = 1`. Sin
    `capture_id` siempre se añade una fila."""
    with conn:
        conn.execute(
            "INSERT INTO classification_log"
            " (ts_utc, text_norm, source, final_kind, final_area, user_corrected, capture_id)"
            " VALUES (?, ?, 'user', ?, ?, ?, ?)"
            " ON CONFLICT(capture_id) DO UPDATE SET ts_utc = excluded.ts_utc,"
            " text_norm = excluded.text_norm, final_kind = excluded.final_kind,"
            " final_area = excluded.final_area, user_corrected = 1",
            (
                to_utc_iso(now()),
                normalize_text(text),
                final_kind,
                final_area,
                int(user_corrected),
                capture_id,
            ),
        )
