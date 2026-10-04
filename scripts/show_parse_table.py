"""Imprime la tabla frase | reloj | resultado REAL del parser de fechas (tabla adversarial).

Ejecuta cada frase de `tests/test_dates_adversarial.py` con su reloj y muestra lo que el
parser devuelve de verdad (no lo esperado). Sirve para revisar a ojo el comportamiento.

Uso (desde la raíz del repositorio, con el entorno virtual activado):
    python scripts/show_parse_table.py              # tabla en formato Markdown
    python scripts/show_parse_table.py --familia domingo   # solo familias que contengan "domingo"

No usa red, ni claves, ni la base de datos. Está fuera del paquete `asistente`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asistente.timeutil import to_local  # noqa: E402
from tests import test_dates_adversarial as table  # noqa: E402

# (nombre de la familia, tabla, ¿usa el flujo completo con repeticiones?)
FAMILIES = [
    ("citas bíblicas", table.BIBLE, False),
    ("marcadores y horas en palabras", table.MARKERS_AND_WORDS, False),
    ("números sueltos y 7.30", table.LOOSE_NUMBERS, False),
    ("domingo", table.DOMINGO, False),
    ("fechas y 29 de febrero", table.DATES, False),
    ("repeticiones", table.SERIES, True),
    ("diario sustantivo o serie", table.DIARIO, True),
    ("candidatos am/pm sin día", table.MERIDIEM, False),
    ("mañana de madrugada", table.TODAY_OR_TOMORROW, False),
]


def _fmt(moment) -> str:
    return to_local(moment, table.TZ).strftime("%Y-%m-%d %H:%M")


def describe_when(result) -> str:
    if result.status == "ok":
        extra = "" if result.has_time else " (hora por defecto)"
        extra += " [am/pm asumido]" if result.meridiem_inferred else ""
        return f"ok {_fmt(result.when_utc)}{extra}"
    if result.status == "ask":
        shown = ", ".join(_fmt(c) for c in result.candidates)
        return f"pregunta {result.reason}" + (f" [{shown}]" if shown else "")
    return "sin fecha"


def describe_schedule(result) -> str:
    if result.kind == "series":
        extra = "" if result.series.has_time else " (hora por defecto)"
        return f"serie {result.series.rrule} primera {_fmt(result.series.first_at_utc)}{extra}"
    if result.kind == "once":
        return "aviso único: " + describe_when(result.when)
    if result.kind == "ask":
        return f"pregunta {result.reason}"
    return "sin fecha"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--familia", default="", help="filtra las familias por texto")
    args = parser.parse_args()
    print("| Familia | Frase | Reloj local | Resultado real |")
    print("|---|---|---|---|")
    for name, rows, uses_schedule in FAMILIES:
        if args.familia.lower() not in name.lower():
            continue
        for phrase, now_local, _expected in rows:
            if uses_schedule:
                text = describe_schedule(table.schedule(phrase, now_local))
            else:
                text = describe_when(table.run(phrase, now_local))
            print(f"| {name} | {phrase} | {now_local} | {text} |")


if __name__ == "__main__":
    main()
