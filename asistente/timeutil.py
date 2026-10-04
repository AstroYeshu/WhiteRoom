"""Tiempo: todo se guarda en UTC (ISO-8601); la zona local solo se usa al mostrar.

El reloj es inyectable: las funciones que dependen de la hora reciben un `Clock`
(por defecto `now`) para poder probarlas con una hora falsa.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
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


def parse_hhmm(text: str) -> time:
    """Lee una hora `HH:MM` (como se guarda en `settings`)."""
    return time.fromisoformat(text.strip())


def is_quiet_hour(moment: datetime, quiet_start: time, quiet_end: time, tz_name: str) -> bool:
    """¿`moment` cae dentro de las horas de silencio (hora local del usuario)?

    El inicio es inclusivo y el fin exclusivo. El rango puede cruzar la medianoche
    (22:00-07:00). Si inicio y fin coinciden, no hay horas de silencio.
    """
    local_time = to_local(moment, tz_name).time().replace(tzinfo=None)
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= local_time < quiet_end
    return local_time >= quiet_start or local_time < quiet_end


def next_quiet_end(moment: datetime, quiet_end: time, tz_name: str) -> datetime:
    """Próximo instante (UTC) en que termina el silencio, a partir de `moment`."""
    local = to_local(moment, tz_name)
    candidate = local.replace(hour=quiet_end.hour, minute=quiet_end.minute, second=0, microsecond=0)
    if candidate <= local:
        # Se suma un día de calendario local (no 24 h) para respetar el cambio de horario.
        candidate = (candidate.replace(tzinfo=None) + timedelta(days=1)).replace(
            tzinfo=ZoneInfo(tz_name)
        )
    return candidate.astimezone(UTC)


def local_day_bounds(moment: datetime, tz_name: str) -> tuple[datetime, datetime]:
    """Inicio (inclusivo) y fin (exclusivo) del día LOCAL de `moment`, en UTC."""
    local = to_local(moment, tz_name)
    start_naive = local.replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    return (
        local_to_utc(start_naive, tz_name),
        local_to_utc(start_naive + timedelta(days=1), tz_name),
    )
