"""Arranque: config, base de datos y canal.

python -m asistente.main             # Telegram (necesita .env)
python -m asistente.main --dry-run   # consola, sin Telegram, sin APIs, sin secretos
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from asistente.bot.handlers import handle_choice, handle_message
from asistente.channels.base import Channel
from asistente.config import ConfigError, Settings, load_settings
from asistente.core.reminders import ReminderEngine
from asistente.db import open_db
from asistente.timeutil import now

logger = logging.getLogger(__name__)

# El dry-run usa su propia base para no mezclar datos de prueba con los reales.
DRY_RUN_DB_PATH = Path("data/dry_run.db")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="asistente", description="Asistente personal")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="consola en lugar de Telegram; no usa red ni secretos",
    )
    return parser.parse_args(argv)


def setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx registra las URLs completas a nivel INFO y la de Telegram lleva el token del bot.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_settings(dry_run_flag: bool) -> Settings:
    """En dry-run ni siquiera se lee el `.env`: no hace falta ningún secreto."""
    if not (dry_run_flag or os.environ.get("DRY_RUN") == "1"):
        load_dotenv(Path.cwd() / ".env")  # solo el del directorio actual, nunca uno "heredado"
    settings = load_settings(os.environ, dry_run=dry_run_flag)
    if settings.dry_run:
        settings = replace(settings, db_path=DRY_RUN_DB_PATH)
    return settings


def build_engine(settings: Settings, conn: sqlite3.Connection, channel: Channel) -> ReminderEngine:
    """El motor de recordatorios, conectado al canal y al reloj real."""
    return ReminderEngine(conn, channel, str(settings.allowed_user_id), settings.tz_name, now)


def _choice_handler(settings: Settings, conn: sqlite3.Connection, channel: Channel):
    """`handle_choice` con la base, el reloj real y la zona del dueño ya conectados."""
    return partial(
        handle_choice,
        channel=channel,
        allowed_user_id=settings.allowed_user_id,
        conn=conn,
        now=now,
        tz_name=settings.tz_name,
    )


def run_console(settings: Settings, conn: sqlite3.Connection) -> None:
    from asistente.channels.console import ConsoleChannel

    # La consola de Windows puede no soportar emojis por defecto.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    channel = ConsoleChannel(user_ref=str(settings.allowed_user_id))
    engine = build_engine(settings, conn, channel)
    asyncio.run(
        channel.serve(
            partial(handle_message, channel=channel, allowed_user_id=settings.allowed_user_id),
            _choice_handler(settings, conn, channel),
            engine.tick,
        )
    )


def run_telegram(settings: Settings, conn: sqlite3.Connection) -> None:
    # Importación tardía: el dry-run nunca carga la librería de Telegram.
    from asistente.channels.telegram import TelegramChannel

    channel = TelegramChannel(settings.telegram_bot_token, settings.allowed_user_id)
    engine = build_engine(settings, conn, channel)
    channel.run_polling(
        partial(handle_message, channel=channel, allowed_user_id=settings.allowed_user_id),
        _choice_handler(settings, conn, channel),
        engine.tick,  # Telegram lo corre cada 30 s y una vez al arrancar (first=0)
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = build_settings(args.dry_run)
    except ConfigError as error:
        print(f"Error de configuración: {error}", file=sys.stderr)
        return 2

    setup_logging(settings.log_level)
    conn = open_db(settings.db_path)
    try:
        logger.info("Arrancando (dry_run=%s)", settings.dry_run)
        if settings.dry_run:
            run_console(settings, conn)
        else:
            run_telegram(settings, conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
