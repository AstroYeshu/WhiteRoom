"""Las pruebas omitidas no pueden crecer en silencio.

El valor esperado vive en `docs/FLUJO.md` ("Pruebas omitidas esperadas: N"). Si una prueba empieza a
omitirse (una condición de entorno que falla, un `skip` nuevo) y nadie actualiza ese número, este
archivo falla. Solo se comprueba cuando se colecciona la suite completa (sin `-k`, `-m` ni rutas).
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLUJO = ROOT / "docs" / "FLUJO.md"
EXPECTED = re.compile(r"Pruebas omitidas esperadas:\s*(\d+)")


def expected_skips(text: str) -> int | None:
    found = EXPECTED.search(text)
    return int(found.group(1)) if found else None


def test_flujo_documenta_el_numero_de_omitidas_esperado():
    assert expected_skips(FLUJO.read_text(encoding="utf-8")) is not None


def test_el_lector_del_numero_esperado():
    assert expected_skips("x\n- Pruebas omitidas esperadas: 12 (motivo)\n") == 12
    assert expected_skips("Pruebas omitidas esperadas: 0") == 0
    assert expected_skips("sin el dato") is None


def test_las_omitidas_por_marca_coinciden_con_el_valor_de_flujo(request):
    config = request.config
    if not getattr(config, "coleccion_completa", False):
        return  # con -k, -m o rutas la cuenta no es la de la suite entera
    wanted = expected_skips(FLUJO.read_text(encoding="utf-8"))
    skipped = config.omitidas_por_marca
    assert len(skipped) == wanted, (
        f"{len(skipped)} pruebas se omiten por marca y docs/FLUJO.md dice {wanted}: "
        f"corrige el entorno o actualiza el valor. Omitidas: {skipped[:5]}"
    )


def runtime_skip_calls() -> list[str]:
    """Llamadas a `pytest.skip(...)` o `importorskip(...)` (invisibles al recolectar)."""
    found = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("skip", "importorskip"):
                    found.append(f"{path.name}:{node.lineno}")
    return found


def test_no_hay_omisiones_en_tiempo_de_ejecucion():
    """Un `pytest.skip(...)` dentro de una prueba no lo ve el conteo por marcas: se prohíbe."""
    assert runtime_skip_calls() == []


def test_el_detector_de_omisiones_en_ejecucion_funciona(tmp_path, monkeypatch):
    sample = tmp_path / "tests"
    sample.mkdir()
    (sample / "test_x.py").write_text("import pytest\ndef test_a():\n    pytest.skip('x')\n")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    assert runtime_skip_calls() == ["test_x.py:3"]


@pytest.mark.parametrize("bad", ["Pruebas omitidas esperadas: x", "omitidas: 3"])
def test_un_formato_incorrecto_no_cuenta_como_valor(bad):
    assert expected_skips(bad) is None
