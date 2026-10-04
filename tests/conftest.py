"""Fixtures compartidas: base en memoria con todas las migraciones y un reloj falso."""

from datetime import UTC, datetime

import pytest

from asistente import db
from tests.fakes import FakeClock

TZ = "America/Mexico_City"


@pytest.fixture
def conn():
    connection = db.open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 3, 21, 30, tzinfo=UTC))  # sábado 15:30 en México
