"""Activa los hooks versionados del proyecto: `git config core.hooksPath .githooks`.

Uso (desde la raíz del repositorio):
    python scripts/install_hooks.py

Solo toca la configuración LOCAL de este repositorio (nunca la global). Se puede repetir sin
problema. El hook de pre-commit corre `pytest -q` y `ruff check .` y bloquea el commit si falla.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

HOOKS_DIR = ".githooks"


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
    done = subprocess.run(
        ["git", "-C", str(root), "config", "core.hooksPath", HOOKS_DIR],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        print("FALLA: git no pudo guardar la configuración.", file=sys.stderr)
        return 1
    print(f"Hooks activados: core.hooksPath = {HOOKS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
