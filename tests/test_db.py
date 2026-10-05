import sqlite3
from pathlib import Path

import pytest

from asistente import db

EXPECTED_TABLES = {
    "areas",
    "tasks",
    "reminders",
    "notes",
    "accounts",
    "ledger",
    "classification_log",
    "learned_rules",
    "settings",
    "usage_log",
    "schema_migrations",
}


@pytest.fixture
def conn():
    connection = db.open_db(":memory:")
    yield connection
    connection.close()


def test_crea_el_esquema_completo(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= names


def test_areas_iniciales(conn):
    rows = conn.execute("SELECT name, description FROM areas ORDER BY id").fetchall()
    assert [r["name"] for r in rows] == ["Universidad", "Proyectos", "Iglesia", "Personal"]
    assert all(r["description"].strip() for r in rows)


def test_settings_iniciales(conn):
    settings = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    assert settings == {
        "briefing_time": "07:30",
        "quiet_start": "22:00",
        "quiet_end": "07:00",
        "auto_threshold": "0.80",
        "ask_threshold": "0.50",
        "default_morning_time": "09:00",
        "daily_proactive_cap": "6",
        "ledger_auto_save": "0",
        "meridiem_ask_range": "5-11",
    }


def test_migrar_dos_veces_es_idempotente(conn):
    assert db.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM areas").fetchone()[0] == 4
    assert conn.execute("SELECT version FROM schema_migrations").fetchall()[0]["version"] == 1


def test_migracion_que_falla_no_queda_a_medias(tmp_path: Path):
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE a (id INTEGER);", encoding="utf-8")
    (tmp_path / "002_mala.sql").write_text(
        "CREATE TABLE b (id INTEGER); INSERT INTO no_existe VALUES (1);", encoding="utf-8"
    )
    connection = db.connect(":memory:")
    with pytest.raises(sqlite3.Error):
        db.migrate(connection, tmp_path)
    tables = {r["name"] for r in connection.execute("SELECT name FROM sqlite_master")}
    assert "a" in tables
    assert "b" not in tables
    versions = [r["version"] for r in connection.execute("SELECT version FROM schema_migrations")]
    assert versions == [1]


def _account(conn) -> int:
    cursor = conn.execute("INSERT INTO accounts (name, created_at) VALUES ('efectivo', 'x')")
    return cursor.lastrowid


def _insert_ledger(conn, account_id: int, kind: str, cents: int) -> None:
    conn.execute(
        "INSERT INTO ledger (ts_utc, account_id, kind, amount_cents) VALUES ('x', ?, ?, ?)",
        (account_id, kind, cents),
    )


def test_ledger_rechaza_gasto_positivo_e_ingreso_negativo(conn):
    account_id = _account(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_ledger(conn, account_id, "expense", 8500)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_ledger(conn, account_id, "income", -100)
    _insert_ledger(conn, account_id, "expense", -8500)
    _insert_ledger(conn, account_id, "adjustment", 250)


def test_claves_foraneas_activas(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _insert_ledger(conn, 999, "income", 100)


def test_tasks_rechaza_estado_invalido(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks (title, status, created_at, updated_at) "
            "VALUES ('t', 'borrada', 'x', 'x')"
        )


def test_wal_activo_en_archivo(tmp_path: Path):
    connection = db.open_db(tmp_path / "sub" / "asistente.db")
    mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    connection.close()
    assert mode == "wal"
