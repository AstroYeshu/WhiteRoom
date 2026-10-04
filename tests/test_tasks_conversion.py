"""Bloque 7a: conversión de la bandeja a recordatorio y Deshacer, cada una en UNA transacción.

Reloj: sábado 2026-10-03 15:30 en México.
"""

import sqlite3
from datetime import timedelta

import pytest

from asistente.core import reminders, tasks


@pytest.fixture
def inbox_task(conn, clock) -> tasks.Task:
    return tasks.create_task(conn, "llevar tarea", clock, source_text="llevar tarea")


def when(clock):
    return clock() + timedelta(hours=3)


def test_convertir_crea_el_recordatorio_y_cierra_la_tarea_como_convertida(conn, clock, inbox_task):
    created = tasks.convert_to_reminder(conn, inbox_task.id, "llevar tarea", when(clock), clock)
    assert created is not None and created.task_id is None and created.status == "pending"
    task = tasks.get_task(conn, inbox_task.id)
    assert (task.status, task.closed_reason) == ("dropped", "converted_to_reminder")


def test_convertir_con_fecha_pasada_no_toca_nada(conn, clock, inbox_task):
    with pytest.raises(reminders.PastReminderError):
        tasks.convert_to_reminder(conn, inbox_task.id, "x", clock() - timedelta(minutes=1), clock)
    assert tasks.get_task(conn, inbox_task.id).status == "open"
    assert reminders.list_pending(conn) == []


def test_convertir_una_tarea_ya_cerrada_devuelve_none_y_no_crea_nada(conn, clock, inbox_task):
    tasks.mark_done(conn, inbox_task.id, clock)
    assert tasks.convert_to_reminder(conn, inbox_task.id, "x", when(clock), clock) is None
    assert reminders.list_pending(conn) == []


def test_deshacer_cancela_el_recordatorio_y_reabre_la_tarea_limpiando_el_motivo(
    conn, clock, inbox_task
):
    created = tasks.convert_to_reminder(conn, inbox_task.id, "x", when(clock), clock)
    assert tasks.undo_reminder_conversion(conn, inbox_task.id, created.id, clock) is True
    assert reminders.get_reminder(conn, created.id).status == "cancelled"
    task = tasks.get_task(conn, inbox_task.id)
    assert (task.status, task.closed_reason, task.closed_at) == ("open", None, None)


def test_deshacer_dos_veces_la_segunda_dice_que_no(conn, clock, inbox_task):
    created = tasks.convert_to_reminder(conn, inbox_task.id, "x", when(clock), clock)
    assert tasks.undo_reminder_conversion(conn, inbox_task.id, created.id, clock) is True
    assert tasks.undo_reminder_conversion(conn, inbox_task.id, created.id, clock) is False


def test_deshacer_con_el_recordatorio_ya_avisado_no_cambia_nada(conn, clock, inbox_task):
    created = tasks.convert_to_reminder(conn, inbox_task.id, "x", when(clock), clock)
    with conn:
        conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (created.id,))
    assert tasks.undo_reminder_conversion(conn, inbox_task.id, created.id, clock) is False
    assert reminders.get_reminder(conn, created.id).status == "sent"
    assert tasks.get_task(conn, inbox_task.id).status == "dropped"


def test_deshacer_es_atomico_si_la_tarea_no_se_puede_reabrir(conn, clock, inbox_task):
    """Si la tarea ya no es una conversión, el recordatorio NO se cancela."""
    created = tasks.convert_to_reminder(conn, inbox_task.id, "x", when(clock), clock)
    with conn:
        conn.execute("UPDATE tasks SET closed_reason = 'discarded' WHERE id = ?", (inbox_task.id,))
    assert tasks.undo_reminder_conversion(conn, inbox_task.id, created.id, clock) is False
    assert reminders.get_reminder(conn, created.id).status == "pending"


def test_reopen_converted_solo_reabre_conversiones(conn, clock, inbox_task):
    assert tasks.reopen_converted(conn, inbox_task.id, clock) is False  # abierta: nada que hacer
    tasks.drop_task(conn, inbox_task.id, clock)  # descartada de verdad
    assert tasks.reopen_converted(conn, inbox_task.id, clock) is False
    assert tasks.get_task(conn, inbox_task.id).closed_reason == "discarded"


def test_reopen_converted_reabre_una_conversion_a_nota(conn, clock, inbox_task):
    tasks.close_as_converted(conn, inbox_task.id, "converted_to_note", clock)
    assert tasks.reopen_converted(conn, inbox_task.id, clock) is True
    assert tasks.get_task(conn, inbox_task.id).status == "open"


def test_convertir_una_serie_guarda_la_rrule(conn, clock, inbox_task):
    created = tasks.convert_to_reminder(
        conn, inbox_task.id, "x", when(clock), clock, rrule="FREQ=DAILY"
    )
    assert created.rrule == "FREQ=DAILY"


def test_si_falla_al_cerrar_la_tarea_no_queda_ningun_recordatorio(conn, clock, inbox_task):
    """Atomicidad: un fallo a mitad de la conversión no deja un recordatorio huérfano."""
    with conn:
        conn.execute(
            "CREATE TRIGGER falla_al_cerrar BEFORE UPDATE OF status ON tasks"
            " BEGIN SELECT RAISE(ABORT, 'falla simulada'); END"
        )
    with pytest.raises(sqlite3.DatabaseError):
        tasks.convert_to_reminder(conn, inbox_task.id, "x", when(clock), clock)
    assert reminders.list_pending(conn) == []
    assert tasks.get_task(conn, inbox_task.id).status == "open"
