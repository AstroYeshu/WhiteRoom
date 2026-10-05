"""Conexión a SQLite (modo WAL) y ejecutor de migraciones solo hacia adelante.

Una migración es `NNN_nombre.sql` o, cuando SQL no alcanza (acentos, comparar sin distinguir
mayúsculas), `NNN_nombre.py` con una función `upgrade(conn)`. Ambas corren dentro de una
transacción: si falla, no queda nada a medias.
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d+)_.+\.(?:sql|py)$")


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
    for path in directory.iterdir():
        match = _MIGRATION_NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def _record(version: int, path: Path) -> str:
    return (
        "INSERT INTO schema_migrations (version, name, applied_at) "
        f"VALUES ({version}, '{path.name}', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))"
    )


def _run_sql_migration(conn: sqlite3.Connection, version: int, path: Path) -> None:
    script = path.read_text(encoding="utf-8")
    conn.executescript(f"BEGIN;\n{script}\n{_record(version, path)};\nCOMMIT;")


def _run_python_migration(conn: sqlite3.Connection, version: int, path: Path) -> None:
    spec = importlib.util.spec_from_file_location(f"migration_{version:03d}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upgrade = getattr(module, "upgrade", None)
    if not callable(upgrade):
        raise RuntimeError(f"La migración {path.name} no define upgrade(conn).")
    conn.execute("BEGIN")
    upgrade(conn)
    conn.execute(_record(version, path))
    conn.execute("COMMIT")


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
        try:
            if path.suffix == ".py":
                _run_python_migration(conn, version, path)
            else:
                _run_sql_migration(conn, version, path)
        except BaseException:
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
