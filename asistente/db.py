"""Conexión a SQLite (modo WAL) y ejecutor de migraciones solo hacia adelante."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d+)_.+\.sql$")


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Abre la base (creando la carpeta si hace falta) con las opciones de seguridad activas."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migration_files(directory: Path) -> list[tuple[int, Path]]:
    found = []
    for path in directory.glob("*.sql"):
        match = _MIGRATION_NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Aplica las migraciones pendientes en orden y devuelve las versiones aplicadas.

    Cada migración corre dentro de una transacción: si falla, no queda a medias.
    Nunca se reaplica ni se revierte una migración ya registrada.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

    applied = []
    for version, path in _migration_files(directory):
        if version in done:
            continue
        script = path.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN;\n{script}\n"
                f"INSERT INTO schema_migrations (version, name, applied_at) "
                f"VALUES ({version}, '{path.name}', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));\n"
                f"COMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def open_db(db_path: Path | str) -> sqlite3.Connection:
    """Conecta y deja la base migrada al esquema más reciente."""
    conn = connect(db_path)
    migrate(conn)
    return conn
