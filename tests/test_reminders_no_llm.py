"""Regla de arquitectura: el motor de recordatorios no depende (ni indirectamente) de ningún LLM.

Recorre las importaciones de `core/reminders.py` y de todo módulo propio que importe, de forma
transitiva, y falla si aparece `asistente.llm`, `asistente.classify`, `anthropic` o `telegram`.
"""

import ast
from pathlib import Path

PACKAGE = "asistente"
PACKAGE_DIR = Path(__file__).resolve().parent.parent / PACKAGE
FORBIDDEN_PREFIXES = ("asistente.llm", "asistente.classify", "anthropic", "telegram")


def _is_forbidden(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PREFIXES)


def _imported_names(path: Path) -> set[str]:
    """Todos los nombres importados. `from a import b` cuenta como `a` y como `a.b`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _module_files(name: str, package: str, package_dir: Path) -> list[Path]:
    """Archivos que se ejecutan al importar `name` (el módulo y los `__init__` de sus paquetes)."""
    if name != package and not name.startswith(package + "."):
        return []
    parts = name.split(".")[1:]
    files = []
    for depth in range(len(parts) + 1):
        base = package_dir.joinpath(*parts[:depth])
        for candidate in (base / "__init__.py", base.with_suffix(".py")):
            if candidate.is_file() and candidate not in files:
                files.append(candidate)
    return files


def find_forbidden(
    start: Path, package: str = PACKAGE, package_dir: Path = PACKAGE_DIR
) -> set[str]:
    """Importaciones prohibidas alcanzables desde `start` (transitivo, solo módulos propios)."""
    pending = [start]
    seen: set[Path] = set()
    offenders: set[str] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imported_names(path):
            if _is_forbidden(name):
                offenders.add(name)
            pending.extend(_module_files(name, package, package_dir))
    return offenders


def test_reminders_no_importa_llm_ni_classify_ni_telegram():
    assert find_forbidden(PACKAGE_DIR / "core" / "reminders.py") == set()


def test_el_detector_ve_importaciones_directas(tmp_path):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    lines = [
        "from asistente.llm.claude import ask",
        "from asistente import classify",
        "import anthropic",
        "import telegram.ext",
    ]
    (package_dir / "direct.py").write_text("\n".join(lines) + "\n")
    found = find_forbidden(package_dir / "direct.py", "pkg", package_dir)
    # `from a import b` también cuenta como `a.b`, por eso puede haber nombres de más.
    assert {"asistente.llm.claude", "asistente.classify", "anthropic", "telegram.ext"} <= found


def test_el_detector_ve_importaciones_transitivas(tmp_path):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    (package_dir / "a.py").write_text("from pkg import b\n")
    (package_dir / "b.py").write_text("from pkg.c import helper\n")
    (package_dir / "c.py").write_text("import anthropic\n")
    assert find_forbidden(package_dir / "a.py", "pkg", package_dir) == {"anthropic"}
    # Y si nadie lo importa, no hay falsos positivos.
    (package_dir / "c.py").write_text("import json\n")
    assert find_forbidden(package_dir / "a.py", "pkg", package_dir) == set()


def test_el_detector_ve_los_init_de_los_paquetes(tmp_path):
    package_dir = tmp_path / "pkg"
    (package_dir / "sub").mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    (package_dir / "sub" / "__init__.py").write_text("import anthropic\n")
    (package_dir / "sub" / "leaf.py").write_text("")
    (package_dir / "a.py").write_text("import pkg.sub.leaf\n")
    assert find_forbidden(package_dir / "a.py", "pkg", package_dir) == {"anthropic"}
