"""Instantánea: docs/MENSAJES.md es EXACTAMENTE lo que hoy ve el usuario.

Si cambias un texto o un botón a propósito, regenera el catálogo y revisa el diff:

    python scripts/show_messages.py

La prueba también hace cumplir las reglas de forma que valen para TODAS las pantallas: ninguna
etiqueta de botón pasa de 22 caracteres y todo lo que sale es HTML válido de Telegram.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from asistente.formato import MAX_LABEL
from tests.htmlcheck import html_problems

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "docs" / "MENSAJES.md"


@pytest.fixture(scope="module")
def generated() -> str:
    spec = importlib.util.spec_from_file_location(
        "show_messages", ROOT / "scripts" / "show_messages.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["show_messages"] = module
    spec.loader.exec_module(module)
    return module.render()


def test_el_catalogo_esta_al_dia(generated):
    committed = CATALOG.read_text(encoding="utf-8")
    assert generated == committed, (
        "docs/MENSAJES.md desactualizado: ejecuta scripts/show_messages.py"
    )


def screens(text: str) -> list[str]:
    return re.findall(r"```text\n(.*?)\n```", text, flags=re.S)


def test_hay_pantallas_en_el_catalogo(generated):
    assert len(screens(generated)) > 80


def test_ninguna_etiqueta_de_boton_pasa_de_22_caracteres(generated):
    too_long = []
    for screen in screens(generated):
        for line in screen.splitlines():
            for label in re.findall(r"\[([^\[\]]+)\]", line) if line.startswith("[") else []:
                if len(label) > MAX_LABEL:
                    too_long.append(label)
    assert too_long == []


def test_todo_lo_que_se_envia_es_html_valido(generated):
    for screen in screens(generated):
        for message in screen.split("\n---\n"):
            body = [line for line in message.splitlines() if not line.startswith("[")]
            body = [line for line in body if line != "(reemplaza el mensaje del botón)"]
            assert html_problems("\n".join(body)) == [], message


def test_las_filas_de_botones_no_tienen_mas_de_dos(generated):
    for screen in screens(generated):
        for line in screen.splitlines():
            if line.startswith("["):
                assert len(re.findall(r"\[[^\[\]]+\]", line)) <= 2, line


def button_labels(text: str) -> list[str]:
    labels = []
    for screen in screens(text):
        for line in screen.splitlines():
            if line.startswith("["):
                labels += re.findall(r"\[([^\[\]]+)\]", line)
    return labels


def test_las_horas_de_los_botones_llevan_am_pm(generated):
    """Una etiqueta con "Hoy"/"Mañana" y una hora termina en am o pm (nunca 18:00)."""
    with_time = [label for label in button_labels(generated) if re.match(r"(Hoy|Mañana) \d", label)]
    assert with_time, "el catálogo debería tener etiquetas con hora"
    assert [label for label in with_time if not re.search(r"\d:\d\d (am|pm)$", label)] == []
