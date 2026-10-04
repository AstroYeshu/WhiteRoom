"""Guarda contra un error ya visto: una `\b` escrita mal (con la shell) se convierte en el
carácter de control 0x08 (retroceso) dentro de una expresión regular y la rompe en silencio."""

import re

import pytest

from asistente.parsing import dates, recurrence

BACKSPACE = chr(8)


def _compiled_patterns(module) -> list[tuple[str, re.Pattern[str]]]:
    return [
        (f"{module.__name__}.{name}", value)
        for name, value in vars(module).items()
        if isinstance(value, re.Pattern)
    ]


@pytest.mark.parametrize("module", [dates, recurrence])
def test_ninguna_expresion_regular_contiene_el_caracter_0x08(module):
    patterns = _compiled_patterns(module)
    assert patterns, "el barrido no encontró expresiones regulares: ¿cambió la estructura?"
    broken = [name for name, pattern in patterns if BACKSPACE in pattern.pattern]
    assert broken == []


def test_el_barrido_detecta_una_expresion_rota():
    rota = re.compile("a" + BACKSPACE + "b")
    assert BACKSPACE in rota.pattern
