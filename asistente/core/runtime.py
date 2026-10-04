"""Estado de ejecución del bot para /estado: datos de salud, nunca textos del usuario.

`RuntimeStatus` vive SOLO en memoria (hora de arranque y hora del último tick): escribirla en la
base en cada tick desgastaría la tarjeta SD de la Raspberry Pi. `collect` solo LEE la base.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from asistente.timeutil import from_utc_iso


@dataclass
class RuntimeStatus:
    """Lo que solo sabe el proceso en marcha; el motor lo actualiza en cada tick."""

    bot_env: str
    db_path: Path
    started_at: datetime
    last_tick_at: datetime | None = None


@dataclass(frozen=True)
class StatusReport:
    bot_env: str
    started_at: datetime
    uptime_seconds: int
    last_tick_at: datetime | None
    last_fired_at: datetime | None
    pending: int
    stopped: int
    schema_version: int | None
    db_size_bytes: int | None


def database_size(db_path: Path) -> int | None:
    """Bytes en disco de la base (archivo principal más el -wal), o None si no es un archivo."""
    if not db_path.is_file():
        return None
    total = db_path.stat().st_size
    wal = db_path.with_name(db_path.name + "-wal")
    if wal.is_file():
        total += wal.stat().st_size
    return total


def collect(conn: sqlite3.Connection, runtime: RuntimeStatus, now: datetime) -> StatusReport:
    """Arma el informe. Solo SELECT: no escribe nada."""
    pending, stopped = conn.execute(
        "SELECT COALESCE(SUM(stop_reason IS NULL), 0), COALESCE(SUM(stop_reason IS NOT NULL), 0)"
        " FROM reminders WHERE status = 'pending'"
    ).fetchone()
    (last_fired,) = conn.execute("SELECT MAX(last_fired_at) FROM reminders").fetchone()
    (schema_version,) = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return StatusReport(
        bot_env=runtime.bot_env,
        started_at=runtime.started_at,
        uptime_seconds=int((now - runtime.started_at).total_seconds()),
        last_tick_at=runtime.last_tick_at,
        last_fired_at=from_utc_iso(last_fired) if last_fired else None,
        pending=pending,
        stopped=stopped,
        schema_version=schema_version,
        db_size_bytes=database_size(runtime.db_path),
    )
