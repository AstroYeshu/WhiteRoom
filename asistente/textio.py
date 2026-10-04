"""Salida de texto de los scripts: siempre UTF-8, sin depender de la página de códigos de la consola
(la consola de Windows usa cp1252 u otra y deforma los acentos)."""

from __future__ import annotations

import sys


def force_utf8_output() -> None:
    """Pone stdout y stderr en UTF-8 si el flujo lo permite (`reconfigure`)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
