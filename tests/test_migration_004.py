"""Migración 004: columnas de detención de recordatorios y `tasks.closed_reason`."""

import asyncio
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from asistente import db
from asistente.channels.base import PermanentChannelError
from asistente.core import reminders, tasks
from asistente.core.reminders import ReminderEngine
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"


def _old_database(tmp_path: Path) -> sqlite3.Connection:
    """Base con las migraciones 001-003 aplicadas y datos 'viejos' (centinela attempts=1000)."""
    old = tmp_path / "migrations_old"
    old.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_")[0]) <= 3:
            shutil.copy(path, old / path.name)
    connection = db.connect(":memory:")
    assert db.migrate(connection, old) == [1, 2, 3]
    connection.executescript(
        """
        INSERT INTO reminders (text, fire_at_utc, attempts, created_at)
          VALUES ('detenido', '2026-10-03T21:30:00+00:00', 1000, 'x'),
                 ('reintentando', '2026-10-03T21:30:00+00:00', 3, 'x');
        INSERT INTO tasks (title, status, created_at, updated_at)
          VALUES ('descartada', 'dropped', 'x', 'x'),
                 ('abierta', 'open', 'x', 'x'),
                 ('hecha', 'done', 'x', 'x');
        """
    )
    connection.commit()
    return connection


def test_migra_datos_viejos_sin_centinela(tmp_path):
    connection = _old_database(tmp_path)
    assert db.migrate(connection) == [4]

    stopped, retrying = connection.execute("SELECT * FROM reminders ORDER BY id").fetchall()
    assert (stopped["stop_reason"], stopped["attempts"]) == ("legacy", 0)
    assert stopped["stopped_at"] is not None
    assert (retrying["stop_reason"], retrying["stopped_at"], retrying["attempts"]) == (
        None,
        None,
        3,
    )
    assert retrying["first_failed_at"] is None

    reasons = {r["title"]: r["closed_reason"] for r in connection.execute("SELECT * FROM tasks")}
    assert reasons == {"descartada": "discarded", "abierta": None, "hecha": None}


def test_closed_reason_rechaza_valores_invalidos(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks (title, status, closed_reason, created_at, updated_at)"
            " VALUES ('t', 'dropped', 'porque_si', 'x', 'x')"
        )
    for reason in ("discarded", "converted_to_reminder", "converted_to_note"):
        conn.execute(
            "INSERT INTO tasks (title, status, closed_reason, created_at, updated_at)"
            " VALUES ('t', 'dropped', ?, 'x', 'x')",
            (reason,),
        )


def test_descartar_guarda_el_motivo(conn, clock):
    task = tasks.create_task(conn, "a", clock)
    assert tasks.drop_task(conn, task.id, clock) is True
    stored = tasks.get_task(conn, task.id)
    assert (stored.status, stored.closed_reason) == ("dropped", "discarded")


def test_hacer_una_tarea_no_pone_motivo(conn, clock):
    task = tasks.create_task(conn, "a", clock)
    tasks.mark_done(conn, task.id, clock)
    assert tasks.get_task(conn, task.id).closed_reason is None


@pytest.mark.parametrize("reason", ["converted_to_reminder", "converted_to_note"])
def test_conversion_de_bandeja_es_dropped_con_su_motivo(conn, clock, reason):
    task = tasks.create_task(conn, "bandeja", clock)
    assert tasks.close_as_converted(conn, task.id, reason, clock) is True
    stored = tasks.get_task(conn, task.id)
    assert (stored.status, stored.closed_reason) == ("dropped", reason)
    assert stored.closed_at is not None
    assert tasks.close_as_converted(conn, task.id, reason, clock) is False  # ya cerrada


def test_conversion_rechaza_motivos_que_no_son_conversion(conn, clock):
    task = tasks.create_task(conn, "bandeja", clock)
    for bad in ("discarded", "otro"):
        with pytest.raises(ValueError):
            tasks.close_as_converted(conn, task.id, bad, clock)
    assert tasks.get_task(conn, task.id).status == "open"


def test_papelera_y_conteos_distinguen_conversiones(conn, clock):
    """/papelera y los reportes filtran por closed_reason='discarded'; las hechas siguen limpias."""
    discarded = tasks.create_task(conn, "descartada", clock)
    converted = tasks.create_task(conn, "convertida", clock)
    done = tasks.create_task(conn, "hecha", clock)
    tasks.drop_task(conn, discarded.id, clock)
    tasks.close_as_converted(conn, converted.id, "converted_to_reminder", clock)
    tasks.mark_done(conn, done.id, clock)

    def titles(where: str) -> list[str]:
        return [r["title"] for r in conn.execute(f"SELECT title FROM tasks WHERE {where}")]

    assert titles("closed_reason = 'discarded'") == ["descartada"]
    assert titles("status = 'done'") == ["hecha"]  # la conversión no infla las hechas


def test_cerrar_una_conversion_cancela_sus_recordatorios(conn, clock):
    task = tasks.create_task(conn, "bandeja", clock, due_at_utc=clock() + timedelta(days=3))
    assert [r for r in reminders.list_pending(conn) if r.task_id == task.id]
    tasks.close_as_converted(conn, task.id, "converted_to_note", clock)
    assert not [r for r in reminders.list_pending(conn) if r.task_id == task.id]


# --- Recordatorios: sin centinela ---------------------------------------------------------------


def test_no_existe_el_centinela_attempts():
    assert not hasattr(reminders, "STOPPED_ATTEMPTS")


def test_detener_usa_columnas_y_no_toca_attempts(conn, clock):
    channel = ScriptedChannel()
    engine = ReminderEngine(conn, channel, "42", TZ, clock)
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    channel.always_fail_with(PermanentChannelError("bot_blocked"))
    asyncio.run(engine.tick())

    stored = reminders.get_reminder(conn, created.id)
    assert stored.stopped is True and stored.status == "pending"
    assert stored.stop_reason == "permanent:bot_blocked"
    assert stored.stopped_at is not None
    assert stored.attempts < 1000


def test_stopped_y_list_due_salen_de_stop_reason(conn, clock):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    assert [r.id for r in reminders.list_due(conn, clock())] == [created.id]
    with conn:
        conn.execute(
            "UPDATE reminders SET stop_reason = 'permanent:x', stopped_at = 'y' WHERE id = ?",
            (created.id,),
        )
    assert reminders.get_reminder(conn, created.id).stopped is True
    assert reminders.list_due(conn, clock()) == []
