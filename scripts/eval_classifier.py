"""Resumen de las etiquetas del dueño en `classification_log`, con UNA fila por captura.

Uso (desde la raíz del repositorio, con el entorno virtual activado):
    python scripts/eval_classifier.py                 # DB_PATH del entorno o del `.env` local
    python scripts/eval_classifier.py --db otra.db

Hoy no compara clasificadores (todavía no los hay: Fase 2); cuenta lo que el dueño decidió, por tipo
y por área, y cuántas capturas corrigió. La base se abre en solo lectura. No usa red ni IA.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asistente.textio import force_utf8_output  # noqa: E402

DEFAULT_DB_PATH = "data/asistente.db"
NO_AREA = "(sin área)"


@dataclass(frozen=True)
class Label:
    final_kind: str
    final_area: str | None
    user_corrected: bool


@dataclass(frozen=True)
class Summary:
    total: int
    by_kind: dict[str, int]
    by_area: dict[str, int]
    corrected: int


def load_labels(conn: sqlite3.Connection) -> list[Label]:
    """Una etiqueta por captura (`capture_id`); las filas sin captura cuentan cada una."""
    rows = conn.execute(
        "SELECT final_kind, final_area, user_corrected FROM classification_log"
        " WHERE source = 'user' ORDER BY id"
    )
    return [Label(row[0] or "", row[1], bool(row[2])) for row in rows]


def summarize(labels: Sequence[Label]) -> Summary:
    kinds = Counter(item.final_kind for item in labels)
    areas = Counter(item.final_area or NO_AREA for item in labels)
    return Summary(
        total=len(labels),
        by_kind=dict(kinds),
        by_area=dict(areas),
        corrected=sum(item.user_corrected for item in labels),
    )


def render(summary: Summary) -> str:
    lines = [
        f"Capturas etiquetadas: {summary.total}",
        f"Corregidas por el dueño: {summary.corrected}",
        "Por tipo:",
        *[f"  {kind}: {count}" for kind, count in sorted(summary.by_kind.items())],
        "Por área:",
        *[f"  {area}: {count}" for area, count in sorted(summary.by_area.items())],
    ]
    return "\n".join(lines)


def open_readonly(path: Path) -> sqlite3.Connection:
    """La base en solo lectura: este script jamás escribe en ella."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume las etiquetas del dueño.")
    parser.add_argument("--db", type=Path, help="base a leer (por defecto, DB_PATH)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_output()
    args = parse_args(argv)
    load_dotenv(Path.cwd() / ".env")  # solo el del directorio actual, como main.py
    path = args.db or Path(os.environ.get("DB_PATH") or DEFAULT_DB_PATH)
    if not path.is_file():
        print(f"FALLA: la base de datos no existe: {path}", file=sys.stderr)
        return 1
    try:
        conn = open_readonly(path)
        try:
            labels = load_labels(conn)
        finally:
            conn.close()
    except sqlite3.Error as error:
        print(f"FALLA: no se pudo leer la base: {type(error).__name__}", file=sys.stderr)
        return 1
    print(render(summarize(labels)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
