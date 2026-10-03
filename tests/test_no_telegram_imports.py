"""Regla de arquitectura: solo `channels/telegram.py` importa la librería de Telegram."""

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "asistente"
ALLOWED = PACKAGE_DIR / "channels" / "telegram.py"
FORBIDDEN_ROOT = "telegram"


def _imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_solo_channels_telegram_importa_telegram():
    offenders = [
        path.relative_to(PACKAGE_DIR).as_posix()
        for path in PACKAGE_DIR.rglob("*.py")
        if path != ALLOWED and FORBIDDEN_ROOT in _imported_roots(path)
    ]
    assert offenders == []


def test_el_detector_funciona():
    """Comprueba que `telegram.py` sí se detecta (si no, el test anterior no probaría nada)."""
    assert FORBIDDEN_ROOT in _imported_roots(ALLOWED)
