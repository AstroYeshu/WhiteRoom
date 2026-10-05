"""Fixtures compartidas: base en memoria con todas las migraciones y un reloj falso."""

import ssl
from datetime import UTC, datetime
from pathlib import Path

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


@pytest.fixture(scope="session", autouse=True)
def _contexto_ssl_en_cache():
    """Construir un `TelegramChannel` crea dos clientes httpx y cada uno carga el almacén de
    certificados (~0,4 s en Windows). Con ~130 pruebas eso era ~80 s de los ~110 s de la suite.
    Las pruebas nunca abren red: comparten un contexto SSL por combinación de argumentos."""
    original = ssl.create_default_context
    cache: dict[tuple, ssl.SSLContext] = {}

    def con_cache(*args, **kwargs):
        clave = (args, tuple(sorted(kwargs.items())))
        if clave not in cache:
            cache[clave] = original(*args, **kwargs)
        return cache[clave]

    ssl.create_default_context = con_cache
    yield
    ssl.create_default_context = original


def _se_omite_por_marca(item) -> bool:
    """¿Lleva una marca `skip` o `skipif` que hoy se cumple? (el conteo de `test_omitidas.py`)"""
    for marker in item.iter_markers():
        if marker.name == "skip":
            return True
        if marker.name == "skipif":
            condition = marker.args[0] if marker.args else marker.kwargs.get("condition")
            if bool(condition):
                return True
    return False


def pytest_collection_modifyitems(config, items):
    """Anota qué pruebas se omitirán por marca y si se coleccionó la suite completa."""
    config.omitidas_por_marca = [item.nodeid for item in items if _se_omite_por_marca(item)]
    root = Path(__file__).resolve().parent.parent
    paths = [Path(arg.split("::")[0]).resolve() for arg in config.args]
    config.coleccion_completa = (
        not config.option.markexpr
        and not config.option.keyword
        and all(path in (root, root / "tests") for path in paths)
    )
