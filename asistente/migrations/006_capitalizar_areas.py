"""Migración 006: la primera letra de cada área pasa a mayúscula (solo si es minúscula).

Es una migración en Python porque SQL no puede: `upper()` de SQLite solo conoce ASCII ("álgebra")
y no hay forma de comparar nombres sin distinguir mayúsculas ni acentos.

- Solo cambia la primera letra y solo si es minúscula ("iOS" y "UNAM" se respetan).
- Si el nombre nuevo chocaría con OTRA área (sin distinguir mayúsculas ni acentos, archivadas
  incluidas), esa área se deja como está: nunca se pisa ni se fusiona nada.
- `classification_log.pred_area` y `final_area` guardan nombres: siguen a las áreas renombradas.
"""

from __future__ import annotations

import sqlite3

from asistente.formato import cap_first
from asistente.parsing.dates import fold


def upgrade(conn: sqlite3.Connection) -> None:
    names = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM areas")}
    for area_id, old in sorted(names.items()):
        new = cap_first(old)
        if new == old:
            continue
        wanted = fold(new)
        if any(other != area_id and fold(name) == wanted for other, name in names.items()):
            continue
        conn.execute("UPDATE areas SET name = ? WHERE id = ?", (new, area_id))
        conn.execute("UPDATE classification_log SET pred_area = ? WHERE pred_area = ?", (new, old))
        conn.execute(
            "UPDATE classification_log SET final_area = ? WHERE final_area = ?", (new, old)
        )
        names[area_id] = new
