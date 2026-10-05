"""Activa los hooks versionados del proyecto: `git config core.hooksPath .githooks`.

Uso (desde la raíz del repositorio):
    python scripts/install_hooks.py

Solo toca la configuración LOCAL de este repositorio (nunca la global). Se puede repetir sin
problema. Instala dos niveles: pre-commit (`ruff check .` y `pytest -q -m "not slow"`) y pre-push
(`pytest -q`, la suite completa). Cualquiera de los dos bloquea la operacion si falla.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

HOOKS_DIR = ".githooks"
HOOK_NAMES = ("pre-commit", "pre-push")


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else default_root()
    inside = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-dir"], capture_output=True, text=True
    )
    if inside.returncode != 0:
        print(f"FALLA: {root} no es un repositorio de git.", file=sys.stderr)
        return 1
    if not (root / HOOKS_DIR).is_dir():
        print(f"FALLA: no existe la carpeta {HOOKS_DIR}/ en {root}.", file=sys.stderr)
        return 1
    missing = [name for name in HOOK_NAMES if not (root / HOOKS_DIR / name).is_file()]
    if missing:
        print(f"FALLA: faltan hooks en {HOOKS_DIR}/: {', '.join(missing)}.", file=sys.stderr)
        return 1
    done = subprocess.run(
        ["git", "-C", str(root), "config", "core.hooksPath", HOOKS_DIR],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        print("FALLA: git no pudo guardar la configuración.", file=sys.stderr)
        return 1
    print(f"Hooks activados: core.hooksPath = {HOOKS_DIR} ({', '.join(HOOK_NAMES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
