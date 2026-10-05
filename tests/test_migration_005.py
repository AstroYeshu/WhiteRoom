"""Migración 005: `classification_log.capture_id` (una fila por captura, ligada a la tarea)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from asistente import db


def old_database(tmp_path: Path, up_to: int = 4) -> sqlite3.Connection:
    """Base con las migraciones 001..`up_to` y filas viejas de `classification_log`."""
    old = tmp_path / "migrations_old"
    old.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_")[0]) <= up_to:
            shutil.copy(path, old / path.name)
    connection = db.connect(":memory:")
    assert db.migrate(connection, old) == list(range(1, up_to + 1))
    connection.executescript(
        """
        INSERT INTO classification_log (ts_utc, text_norm, source, final_kind, final_area)
          VALUES ('2026-10-03T21:30:00+00:00', 'comprar pan', 'user', 'task', 'personal'),
                 ('2026-10-03T21:31:00+00:00', 'llamar a mama', 'user', 'reminder', NULL);
        """
    )
    connection.commit()
    return connection


def columns(connection) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in connection.execute("PRAGMA table_info(classification_log)")}


def test_existe_el_archivo_005_y_es_el_siguiente_numero_libre():
    names = sorted(path.name for path in db.MIGRATIONS_DIR.glob("*.sql"))
    assert names[:5] == [
        "001_init.sql",
        "002_reminders_nag_count.sql",
        "003_meridiem_ask_range.sql",
        "004_reminder_stops_task_closed_reason.sql",
        "005_classification_capture_id.sql",
    ]


def test_aplica_solo_la_005_a_una_base_en_la_004(tmp_path):
    connection = old_database(tmp_path)
    assert "capture_id" not in columns(connection)
    assert db.migrate(connection) == [5]
    assert "capture_id" in columns(connection)
    assert db.migrate(connection) == []  # no se repite


def test_conserva_las_filas_viejas_con_capture_id_nulo(tmp_path):
    connection = old_database(tmp_path)
    db.migrate(connection)
    rows = connection.execute("SELECT * FROM classification_log ORDER BY id").fetchall()
    assert [r["text_norm"] for r in rows] == ["comprar pan", "llamar a mama"]
    assert [r["capture_id"] for r in rows] == [None, None]
    assert [r["final_kind"] for r in rows] == ["task", "reminder"]


def test_la_columna_es_entera_y_admite_nulos():
    connection = db.open_db(":memory:")
    column = columns(connection)["capture_id"]
    assert column["type"] == "INTEGER" and column["notnull"] == 0


def test_hay_a_lo_sumo_una_fila_por_captura():
    connection = db.open_db(":memory:")
    connection.execute(
        "INSERT INTO tasks (id, title, created_at, updated_at) VALUES (1, 'x', 'x', 'x')"
    )
    insert = (
        "INSERT INTO classification_log (ts_utc, text_norm, source, capture_id)"
        " VALUES ('x', 'x', 'user', ?)"
    )
    connection.execute(insert, (1,))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(insert, (1,))


def test_varias_filas_sin_captura_son_validas():
    connection = db.open_db(":memory:")
    insert = (
        "INSERT INTO classification_log (ts_utc, text_norm, source, capture_id)"
        " VALUES ('x', 'x', 'user', NULL)"
    )
    connection.execute(insert)
    connection.execute(insert)
    assert connection.execute("SELECT COUNT(*) FROM classification_log").fetchone()[0] == 2


def test_la_captura_debe_ser_una_tarea_que_existe():
    connection = db.open_db(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO classification_log (ts_utc, text_norm, source, capture_id)"
            " VALUES ('x', 'x', 'user', 999)"
        )


def test_la_migracion_queda_registrada():
    connection = db.open_db(":memory:")
    row = connection.execute("SELECT name FROM schema_migrations WHERE version = 5").fetchone()
    assert row["name"] == "005_classification_capture_id.sql"


def test_la_llave_foranea_apunta_a_tasks():
    connection = db.open_db(":memory:")
    keys = connection.execute("PRAGMA foreign_key_list(classification_log)").fetchall()
    assert [(row["from"], row["table"]) for row in keys] == [("capture_id", "tasks")]
