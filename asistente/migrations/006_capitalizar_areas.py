"""Migración 006: la primera letra de cada área pasa a mayúscula (solo si es minúscula).

Es una migración en Python porque SQL no puede: `upper()` de SQLite solo conoce ASCII ("álgebra")
y no hay forma de comparar nombres sin distinguir mayúsculas ni acentos.

AUTOCONTENIDA: usa solo la biblioteca estándar y NO importa nada del paquete `asistente`. Una
migración ya publicada no debe cambiar de comportamiento si mañana cambian `formato.cap_first` o
`parsing.dates.fold`: por eso la regla de mayúscula y la comparación sin acentos viven aquí.

- Solo cambia la primera letra y solo si es minúscula ("iOS", "eBay" y "UNAM" se respetan: una
  primera palabra con otra mayúscula después de su primera letra no se toca).
- Salta los "¿" y "¡" iniciales ("¿qué?" pasa a "¿Qué?").
- Si el nombre nuevo chocaría con OTRA área (sin distinguir mayúsculas ni acentos, archivadas
  incluidas), esa área se deja como está: nunca se pisa ni se fusiona nada.
- `classification_log.pred_area` y `final_area` guardan nombres: siguen a las áreas renombradas.
- Idempotente: con las áreas ya en mayúscula no hay nada que cambiar.
"""

from __future__ import annotations

import sqlite3
import unicodedata

_OPENING_MARKS = "¿¡"


def _cap_first(text: str) -> str:
    """Primera letra en mayúscula solo si es minúscula (copia congelada de `formato.cap_first`)."""
    start = len(text) - len(text.lstrip(_OPENING_MARKS))
    if start == len(text) or not text[start].islower():
        return text
    first_word = text[start:].split(maxsplit=1)[0]
    if any(char.isupper() for char in first_word[1:]):
        return text
    upper = text[start].upper()
    if len(upper) != 1:  # "ß".upper() es "SS": no cambia la longitud del texto
        return text
    return text[:start] + upper + text[start + 1 :]


def _fold(text: str) -> str:
    """Minúsculas y sin acentos, 1 carácter -> 1 carácter (copia de `parsing.dates.fold`)."""
    return "".join(unicodedata.normalize("NFD", ch)[0].lower()[:1] for ch in text)


def upgrade(conn: sqlite3.Connection) -> None:
    # Por posición, no por nombre de columna: no depende del `row_factory` de la conexión.
    names = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM areas")}
    for area_id, old in sorted(names.items()):
        new = _cap_first(old)
        if new == old:
            continue
        wanted = _fold(new)
        if any(other != area_id and _fold(name) == wanted for other, name in names.items()):
            continue
        conn.execute("UPDATE areas SET name = ? WHERE id = ?", (new, area_id))
        conn.execute("UPDATE classification_log SET pred_area = ? WHERE pred_area = ?", (new, old))
        conn.execute(
            "UPDATE classification_log SET final_area = ? WHERE final_area = ?", (new, old)
        )
        names[area_id] = new
