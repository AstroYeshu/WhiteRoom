"""Localiza `sh` para las pruebas que ejecutan los hooks (`sh .githooks/...`)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

# Dónde deja Git for Windows su `sh`, respecto a la carpeta de instalación.
_SH_RELATIVE = (Path("bin") / "sh.exe", Path("usr") / "bin" / "sh.exe")


def find_sh(which: Callable[[str], str | None] = shutil.which) -> str | None:
    """`sh` del PATH; si no está (PowerShell en Windows), el de Git for Windows junto a `git`.

    Sube desde `git` (cmd/git.exe, mingw64/bin/git.exe...) hasta 3 carpetas buscando `bin/sh.exe`
    o `usr/bin/sh.exe`. Sin `sh` por ningún lado devuelve None.
    """
    found = which("sh")
    if found:
        return found
    git = which("git")
    if not git:
        return None
    for parent in list(Path(git).parents)[:3]:
        for relative in _SH_RELATIVE:
            candidate = parent / relative
            if candidate.is_file():
                return str(candidate)
    return None
