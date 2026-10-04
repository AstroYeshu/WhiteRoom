"""Respaldo diario de la base de datos (API de respaldo del módulo `sqlite3`, sin el binario).

Uso (desde la raíz del repositorio, con el entorno virtual activado):
    python scripts/backup_db.py                           # DB_PATH -> <carpeta de la base>/backups/
    python scripts/backup_db.py --db otra.db --dir /mnt/ssd/respaldos

Guarda `asistente-AAAA-MM-DD.db` (repetir el mismo día lo reemplaza), comprueba que la copia
esté íntegra y borra los respaldos de 14 días o más. Termina con código 0 si todo salió bien y con
código 1 si algo falló (para que cron o systemd lo noten). Lee `DB_PATH` del entorno o del `.env`
del directorio actual, igual que `main.py`. No imprime datos de la base.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

RETENTION_DAYS = 14
DEFAULT_DB_PATH = "data/asistente.db"
_NAME = re.compile(r"^asistente-(\d{4}-\d{2}-\d{2})\.db$")


class BackupError(Exception):
    """El respaldo no se pudo hacer o no quedó íntegro."""


def backup_path(target_dir: Path, day: date) -> Path:
    return target_dir / f"asistente-{day.isoformat()}.db"


def _integrity_ok(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError:  # tan dañada que ni siquiera se puede revisar
        return False
    return row is not None and row[0] == "ok"


def _copy(source: Path, tmp: Path) -> None:
    """Copia con `Connection.backup` (consistente aunque el bot esté escribiendo) y la verifica."""
    if not source.is_file():
        raise BackupError(f"la base de datos no existe: {source}")
    try:
        src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error as exc:
        raise BackupError(f"no se pudo abrir la base: {exc}") from exc
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            if not _integrity_ok(dst):
                raise BackupError("la copia no pasó la verificación de integridad")
        finally:
            dst.close()
    except sqlite3.Error as exc:
        raise BackupError(f"falló la copia: {exc}") from exc
    finally:
        src.close()


def prune(target_dir: Path, today: date, keep_days: int = RETENTION_DAYS) -> list[Path]:
    """Borra los respaldos de `keep_days` días o más. Solo toca `asistente-AAAA-MM-DD.db`."""
    limit = today - timedelta(days=keep_days)
    removed = []
    for path in sorted(target_dir.iterdir()):
        match = _NAME.match(path.name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if day <= limit:
            path.unlink()
            removed.append(path)
    return removed


def backup(source: Path, target_dir: Path, today: date) -> Path:
    """Hace el respaldo de hoy y poda los viejos (solo si el respaldo salió bien)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    final = backup_path(target_dir, today)
    tmp = final.with_name(final.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        _copy(source, tmp)
        os.replace(tmp, final)  # atómico: un respaldo bueno nunca queda a medias
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    prune(target_dir, today)
    return final


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Respalda la base de datos del asistente.")
    parser.add_argument("--db", type=Path, help="base a respaldar (por defecto, DB_PATH)")
    parser.add_argument("--dir", type=Path, help="carpeta de destino (por defecto, backups/)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, today: date | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(Path.cwd() / ".env")  # solo el del directorio actual, como main.py
    source = args.db or Path(os.environ.get("DB_PATH") or DEFAULT_DB_PATH)
    target_dir = args.dir or source.parent / "backups"
    try:
        result = backup(source, target_dir, today or datetime.now().date())
    except (BackupError, OSError) as exc:
        print(f"FALLA el respaldo: {exc}", file=sys.stderr)
        return 1
    print(f"Respaldo listo: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
