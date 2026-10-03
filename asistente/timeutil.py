"""Tiempo: todo se guarda en UTC (ISO-8601); la zona local solo se usa al mostrar.

El reloj es inyectable: las funciones que dependen de la hora reciben un `Clock`
(por defecto `now`) para poder probarlas con una hora falsa.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

Clock = Callable[[], datetime]


def now() -> datetime:
    """Hora actual en UTC (con zona horaria)."""
    return datetime.now(UTC)


def to_utc_iso(moment: datetime) -> str:
    """Convierte un datetime con zona a texto ISO-8601 en UTC, listo para guardar."""
    if moment.tzinfo is None:
        raise ValueError("Se necesita un datetime con zona horaria")
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def from_utc_iso(text: str) -> datetime:
    """Lee un texto ISO-8601 guardado en la base y lo devuelve como datetime UTC."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError("El texto ISO-8601 no trae zona horaria")
    return moment.astimezone(UTC)


def to_local(moment: datetime, tz_name: str) -> datetime:
    """Pasa un datetime a la zona del usuario (solo para mostrar)."""
    return moment.astimezone(ZoneInfo(tz_name))


def local_to_utc(naive_local: datetime, tz_name: str) -> datetime:
    """Interpreta una fecha/hora sin zona como hora local del usuario y la pasa a UTC."""
    if naive_local.tzinfo is not None:
        raise ValueError("Se esperaba un datetime sin zona horaria")
    return naive_local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)
