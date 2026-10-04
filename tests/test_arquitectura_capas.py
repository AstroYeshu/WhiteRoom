"""Capas: el formato es un módulo neutral y `core/` no depende de `bot/`.

- `asistente/formato.py` (presentación pura) no importa, ni de forma transitiva, nada de `bot/`,
  `core/`, `classify/`, `llm/`, `anthropic` ni `telegram`.
- Ningún módulo de `core/` importa nada de `asistente.bot` (la conversación depende del núcleo,
  no al revés). El test de `reminders.py` sin LLM sigue en `test_reminders_no_llm.py`.
"""

from pathlib import Path

import pytest

from tests.test_reminders_no_llm import PACKAGE_DIR, _imported_names, _module_files

NEUTRAL_FORBIDDEN = (
    "asistente.bot",
    "asistente.core",
    "asistente.classify",
    "asistente.llm",
    "anthropic",
    "telegram",
)


def _matches(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def reachable_forbidden(
    start: Path,
    prefixes: tuple[str, ...],
    package: str = "asistente",
    package_dir: Path = PACKAGE_DIR,
) -> set[str]:
    """Importaciones prohibidas alcanzables desde `start` (transitivo, solo módulos propios)."""
    pending, seen, found = [start], set(), set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imported_names(path):
            if _matches(name, prefixes):
                found.add(name)
            pending.extend(_module_files(name, package, package_dir))
    return found


def test_formato_es_un_modulo_neutral():
    formato = PACKAGE_DIR / "formato.py"
    assert formato.is_file()
    assert reachable_forbidden(formato, NEUTRAL_FORBIDDEN) == set()


def test_las_opciones_son_un_modulo_neutral():
    choices = PACKAGE_DIR / "choices.py"
    assert choices.is_file()
    assert reachable_forbidden(choices, NEUTRAL_FORBIDDEN) == set()


@pytest.mark.parametrize("path", sorted((PACKAGE_DIR / "core").glob("*.py")), ids=lambda p: p.name)
def test_core_no_importa_nada_de_bot(path):
    assert reachable_forbidden(path, ("asistente.bot",)) == set()


def test_el_detector_ve_una_importacion_prohibida(tmp_path):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    (package_dir / "bot").mkdir()
    (package_dir / "bot" / "__init__.py").write_text("")
    (package_dir / "bot" / "x.py").write_text("VALUE = 1\n")
    (package_dir / "middle.py").write_text("from pkg.bot import x\n")
    (package_dir / "start.py").write_text("import pkg.middle\n")
    found = reachable_forbidden(package_dir / "start.py", ("pkg.bot",), "pkg", package_dir)
    assert "pkg.bot" in found  # alcanzado de forma transitiva, a través de `middle`
