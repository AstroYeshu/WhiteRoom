"""Áreas de la vida del usuario (universidad, proyectos...). Nunca se borran: se archivan."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from asistente.formato import cap_first
from asistente.parsing.dates import fold
from asistente.timeutil import Clock, to_utc_iso

MAX_NAME_LENGTH = 40


class AreaError(ValueError):
    """Nombre de área inválido o repetido (el mensaje está pensado para mostrarse al usuario)."""


@dataclass(frozen=True)
class Area:
    id: int
    name: str
    description: str
    archived: bool


def _from_row(row: sqlite3.Row) -> Area:
    return Area(row["id"], row["name"], row["description"], bool(row["archived"]))


def list_areas(conn: sqlite3.Connection, include_archived: bool = False) -> list[Area]:
    sql = "SELECT * FROM areas"
    if not include_archived:
        sql += " WHERE archived = 0"
    return [_from_row(row) for row in conn.execute(sql + " ORDER BY id")]


def get_area(conn: sqlite3.Connection, area_id: int) -> Area | None:
    row = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
    return _from_row(row) if row else None


def find_area_by_name(conn: sqlite3.Connection, name: str) -> Area | None:
    """Busca sin distinguir mayúsculas ni acentos entre las áreas no archivadas."""
    wanted = fold(name.strip())
    return next((area for area in list_areas(conn) if fold(area.name) == wanted), None)


def validate_new_name(conn: sqlite3.Connection, name: str) -> str:
    """El nombre normalizado de un área nueva, o `AreaError` (vacío, largo o repetido).

    Normalizar = recortar, colapsar espacios y poner en mayúscula SOLO la primera letra si es
    minúscula (`cap_first`: "iOS" y "UNAM" se respetan).

    Es único sin distinguir mayúsculas ni acentos, y las áreas archivadas también reservan su
    nombre (si no, habría dos «Viajes» y no se sabría a cuál se refiere el usuario).
    """
    name = cap_first(" ".join(name.split()))
    if not name:
        raise AreaError("El área necesita un nombre.")
    if len(name) > MAX_NAME_LENGTH:
        raise AreaError(f"El nombre es demasiado largo (máximo {MAX_NAME_LENGTH} caracteres).")
    wanted = fold(name)
    for existing in list_areas(conn, include_archived=True):
        if fold(existing.name) == wanted:
            archived = " (archivada)" if existing.archived else ""
            raise AreaError(f"Ya existe un área llamada «{cap_first(existing.name)}»{archived}.")
    return name


def create_area(conn: sqlite3.Connection, name: str, description: str, now: Clock) -> Area:
    """Crea un área. La descripción puede quedar vacía ("sin descripción"): el clasificador la
    ignora hasta que tenga una."""
    name = validate_new_name(conn, name)
    description = " ".join(description.split())
    with conn:
        cursor = conn.execute(
            "INSERT INTO areas (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, to_utc_iso(now())),
        )
    area = get_area(conn, cursor.lastrowid)
    assert area is not None
    return area


def archive_area(conn: sqlite3.Connection, area_id: int) -> None:
    """Soft delete: el área deja de ofrecerse, pero lo ya guardado conserva su referencia."""
    with conn:
        conn.execute("UPDATE areas SET archived = 1 WHERE id = ?", (area_id,))
