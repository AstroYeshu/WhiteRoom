"""DEUDA CONOCIDA (no se arregla en la Fase 1): horario de verano, horas inexistentes o repetidas.

En Nueva York, el 14 de marzo de 2027 los relojes saltan de las 02:00 a las 03:00 (la 02:30
no existe) y el 1 de noviembre de 2026 la 01:30 ocurre dos veces. El parser acepta esas horas
y elige una en silencio. Lo correcto, por el principio "lo que no se entendió se pregunta",
es preguntar. Las pruebas están marcadas `xfail(strict=True)`: cuando se arregle, fallarán
(XPASS) y habrá que quitar la marca. Ver "Deuda conocida" en docs/PLAN_FASE1.md.
"""

from datetime import datetime, time

import pytest

from asistente.parsing.dates import parse_when
from asistente.timeutil import local_to_utc

NEW_YORK = "America/New_York"


def parse(text: str, now_local: str):
    now = local_to_utc(datetime.strptime(now_local, "%Y-%m-%d %H:%M"), NEW_YORK)
    return parse_when(text, lambda: now, NEW_YORK, time(9, 0))


@pytest.mark.xfail(strict=True, reason="deuda conocida: la hora 02:30 no existe ese día (salto)")
def test_hora_inexistente_por_el_salto_de_primavera_se_pregunta():
    result = parse("14 de marzo 2:30 am", "2027-03-01 10:00")
    assert result.status == "ask"


@pytest.mark.xfail(strict=True, reason="deuda conocida: la hora 01:30 ocurre dos veces ese día")
def test_hora_repetida_por_el_cambio_de_otono_se_pregunta():
    result = parse("1 de noviembre 1:30 am", "2026-10-20 10:00")
    assert result.status == "ask"


def test_hoy_el_parser_no_falla_en_esas_horas_pero_las_acepta_en_silencio():
    # Documenta el comportamiento actual (la deuda): no hay excepción y devuelve "ok".
    assert parse("14 de marzo 2:30 am", "2027-03-01 10:00").status == "ok"
    assert parse("1 de noviembre 1:30 am", "2026-10-20 10:00").status == "ok"
