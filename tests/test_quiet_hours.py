"""Horas de silencio: rango normal, cruce de medianoche, bordes y zonas horarias."""

from datetime import UTC, datetime, time, timedelta

import pytest

from asistente.timeutil import is_quiet_hour, next_quiet_end, parse_hhmm

TZ = "America/Mexico_City"  # UTC-6 todo el año desde 2022
NIGHT = (time(22, 0), time(7, 0))
DAY = (time(13, 0), time(15, 0))


def local(hour: int, minute: int = 0, day: int = 10) -> datetime:
    """Una hora local de México expresada en UTC (como llega del reloj)."""
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC) + timedelta(hours=6)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (21, 59, False),
        (22, 0, True),  # inicio inclusivo
        (23, 30, True),
        (3, 0, True),
        (6, 59, True),
        (7, 0, False),  # fin exclusivo
        (12, 0, False),
    ],
)
def test_rango_que_cruza_medianoche(hour, minute, expected):
    assert is_quiet_hour(local(hour, minute), *NIGHT, TZ) is expected


@pytest.mark.parametrize(
    ("hour", "expected"), [(12, False), (13, True), (14, True), (15, False), (23, False)]
)
def test_rango_normal(hour, expected):
    assert is_quiet_hour(local(hour), *DAY, TZ) is expected


def test_inicio_igual_a_fin_no_hay_silencio():
    assert is_quiet_hour(local(3), time(7, 0), time(7, 0), TZ) is False


def test_usa_la_hora_local_no_la_utc():
    # 04:00 UTC = 22:00 en México -> silencio; a las 04:00 UTC en Madrid sería de día.
    moment = datetime(2026, 3, 11, 4, 0, tzinfo=UTC)
    assert is_quiet_hour(moment, *NIGHT, "America/Mexico_City") is True
    assert is_quiet_hour(moment, *NIGHT, "Europe/Madrid") is True  # 05:00 local, aún silencio
    assert is_quiet_hour(moment.replace(hour=10), *NIGHT, "Europe/Madrid") is False


def test_parse_hhmm():
    assert parse_hhmm("22:00") == time(22, 0)
    assert parse_hhmm(" 07:30 ") == time(7, 30)


def test_next_quiet_end_misma_noche_y_dia_siguiente():
    # A las 23:00 locales, el silencio termina mañana a las 07:00 locales.
    assert next_quiet_end(local(23), time(7, 0), TZ) == local(7, day=11)
    # A las 03:00 locales, termina hoy a las 07:00.
    assert next_quiet_end(local(3), time(7, 0), TZ) == local(7)
    # Justo a las 07:00 ya terminó: el siguiente fin es mañana.
    assert next_quiet_end(local(7), time(7, 0), TZ) == local(7, day=11)
