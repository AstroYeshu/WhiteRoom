"""Lectura y validación de la configuración (variables de entorno / `.env`).

`load_settings` recibe el entorno como un diccionario, así los tests nunca
dependen del `.env` real. Quien arranca la app (`main.py`) es quien carga el `.env`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VALID_CLASSIFIERS = ("rules+jev", "rules+haiku")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Cada cuánto revisa el motor lo vencido. Un aviso llega entre 0 y TICK_SECONDS s tarde.
DEFAULT_TICK_SECONDS = 30
MIN_TICK_SECONDS = 5
MAX_TICK_SECONDS = 60

# En --dry-run no hay ID real de Telegram: la consola actúa como este usuario.
DRY_RUN_USER_ID = 1


class ConfigError(Exception):
    """La configuración falta o es inválida. El mensaje nunca incluye valores secretos."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = field(repr=False)
    allowed_user_id: int
    assistant_anthropic_key: str = field(repr=False)
    claude_model_fast: str
    typesafe_api_key: str = field(repr=False)
    typesafe_base_url: str
    classifier: str
    tz_name: str
    currency_code: str
    db_path: Path
    monthly_api_budget_cents: int  # dinero siempre en enteros, nunca float
    dry_run: bool
    log_level: str
    tick_seconds: int = DEFAULT_TICK_SECONDS


def _is_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "si", "sí"}


def _tick_seconds(raw: str) -> int:
    try:
        seconds = int(raw)
    except ValueError:
        seconds = 0
    if not MIN_TICK_SECONDS <= seconds <= MAX_TICK_SECONDS:
        raise ConfigError(
            f"TICK_SECONDS debe ser un entero entre {MIN_TICK_SECONDS} y {MAX_TICK_SECONDS}"
        )
    return seconds


def _budget_to_cents(raw: str) -> int:
    try:
        cents = Decimal(raw) * 100
    except InvalidOperation as exc:
        raise ConfigError("MONTHLY_API_BUDGET_USD debe ser un número") from exc
    if cents < 0 or cents != cents.to_integral_value():
        raise ConfigError("MONTHLY_API_BUDGET_USD debe ser positivo y con máximo 2 decimales")
    return int(cents)


def load_settings(env: Mapping[str, str], dry_run: bool = False) -> Settings:
    """Construye `Settings` desde `env`. Un valor vacío cuenta como ausente.

    `dry_run=True` (o `DRY_RUN=1`) no exige ningún secreto ni dato del usuario.
    """

    def get(name: str, default: str = "") -> str:
        return (env.get(name) or "").strip() or default

    dry_run = dry_run or _is_true(get("DRY_RUN", "0"))

    # Lo que no es opcional fuera de dry-run (solo nombres, nunca valores).
    required = ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "TZ_NAME", "CURRENCY_CODE")
    if not dry_run:
        missing = [name for name in required if not get(name)]
        if missing:
            raise ConfigError("Faltan variables obligatorias: " + ", ".join(missing))

    raw_user_id = get("ALLOWED_USER_ID", str(DRY_RUN_USER_ID))
    try:
        allowed_user_id = int(raw_user_id)
    except ValueError as exc:
        raise ConfigError("ALLOWED_USER_ID debe ser un número entero") from exc

    tz_name = get("TZ_NAME", "UTC")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"TZ_NAME no es una zona IANA válida: {tz_name}") from exc

    classifier = get("CLASSIFIER", "rules+jev")
    if classifier not in VALID_CLASSIFIERS:
        raise ConfigError("CLASSIFIER debe ser uno de: " + ", ".join(VALID_CLASSIFIERS))

    log_level = get("LOG_LEVEL", "INFO").upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError("LOG_LEVEL debe ser uno de: " + ", ".join(VALID_LOG_LEVELS))

    return Settings(
        telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
        allowed_user_id=allowed_user_id,
        assistant_anthropic_key=get("ASSISTANT_ANTHROPIC_KEY"),
        claude_model_fast=get("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001"),
        typesafe_api_key=get("TYPESAFE_API_KEY"),
        typesafe_base_url=get("TYPESAFE_BASE_URL", "https://api.typesafe.ai"),
        classifier=classifier,
        tz_name=tz_name,
        currency_code=get("CURRENCY_CODE", "USD").upper(),
        db_path=Path(get("DB_PATH", "data/asistente.db")),
        monthly_api_budget_cents=_budget_to_cents(get("MONTHLY_API_BUDGET_USD", "8")),
        dry_run=dry_run,
        log_level=log_level,
        tick_seconds=_tick_seconds(get("TICK_SECONDS", str(DEFAULT_TICK_SECONDS))),
    )
