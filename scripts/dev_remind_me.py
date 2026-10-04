"""Crea un recordatorio de prueba "en N minutos" en la base REAL (`DB_PATH`), sin LLM.

Sirve para probar de punta a punta antes del bloque 7: crea el recordatorio con el motor, arranca
el bot (`python -m asistente.main`) en tu propia terminal y espera a que llegue con sus botones.

Uso (desde la raíz del repositorio, con el entorno virtual activado):
    python scripts/dev_remind_me.py 2                       # en 2 minutos
    python scripts/dev_remind_me.py 5 "llevar tarea"        # con texto propio
    python scripts/dev_remind_me.py 30 --urgente            # prioridad 2: se salta el silencio

Lee `DB_PATH` y `TZ_NAME` del entorno o del `.env` del directorio actual (igual que `main.py`).
No necesita ningún secreto, no usa red y NO escribe nada más que ese recordatorio.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asistente.config import ConfigError, load_settings  # noqa: E402
from asistente.core import reminders  # noqa: E402
from asistente.core.settings import get_time_setting  # noqa: E402
from asistente.db import open_db  # noqa: E402
from asistente.parsing.dates import format_when  # noqa: E402
from asistente.timeutil import Clock, is_quiet_hour  # noqa: E402
from asistente.timeutil import now as real_now

DEFAULT_TEXT = "Recordatorio de prueba"


def positive_minutes(raw: str) -> int:
    """Argumento `minutos`: un entero mayor que cero."""
    try:
        minutes = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"«{raw}» no es un número entero de minutos") from None
    if minutes < 1:
        raise argparse.ArgumentTypeError("los minutos deben ser 1 o más")
    return minutes


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dev_remind_me", description="Crea un recordatorio de prueba en N minutos."
    )
    parser.add_argument("minutes", type=positive_minutes, metavar="minutos")
    parser.add_argument("text", nargs="*", metavar="texto", help=f"por defecto: {DEFAULT_TEXT!r}")
    parser.add_argument(
        "--urgente", action="store_true", help="prioridad 2: se salta las horas de silencio"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, now: Clock = real_now) -> int:
    args = parse_args(argv)
    load_dotenv(Path.cwd() / ".env")  # solo el del directorio actual, como main.py
    try:
        # dry_run=True: aquí no hacen falta el token ni el ID de Telegram, solo DB_PATH y TZ_NAME.
        settings = load_settings(os.environ, dry_run=True)
    except ConfigError as error:
        print(f"Error de configuración: {error}", file=sys.stderr)
        return 2

    fire_at = now() + timedelta(minutes=args.minutes)
    conn = open_db(settings.db_path)
    try:
        created = reminders.create_reminder(
            conn,
            " ".join(args.text) or DEFAULT_TEXT,
            fire_at,
            now,
            priority=2 if args.urgente else 1,
        )
        in_silence = is_quiet_hour(
            fire_at,
            get_time_setting(conn, "quiet_start"),
            get_time_setting(conn, "quiet_end"),
            settings.tz_name,
        )
    finally:
        conn.close()

    when = format_when(fire_at, settings.tz_name, now)
    print(f"Recordatorio #{created.id} creado para {when} (en {args.minutes} min).")
    print(f"Base: {settings.db_path}")
    if in_silence and not args.urgente:
        print(
            "Ojo: esa hora cae en las horas de silencio y el aviso quedará retenido hasta que "
            "terminen. Usa --urgente para probar ahora."
        )
    print("Arranca el bot en tu terminal: python -m asistente.main")
    return 0


if __name__ == "__main__":
    # La consola de Windows puede no soportar acentos ni emojis por defecto (igual que main.py).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
