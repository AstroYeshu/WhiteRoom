"""Áreas, tareas y notas: crear, listar y cerrar sin borrar nada."""

from datetime import UTC, datetime, timedelta

import pytest

from asistente.core import areas, notes, tasks
from asistente.timeutil import local_day_bounds, to_utc_iso

TZ = "America/Mexico_City"


# --- Migración 002 -------------------------------------------------------------------------


def test_migracion_002_agrega_nag_count(conn):
    columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(reminders)")}
    assert "nag_count" in columns
    assert columns["nag_count"]["notnull"] == 1
    assert columns["nag_count"]["dflt_value"] == "0"
    versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert versions[:2] == [1, 2]


# --- Áreas ---------------------------------------------------------------------------------


def test_areas_iniciales_y_busqueda_sin_acentos(conn):
    assert [a.name for a in areas.list_areas(conn)] == [
        "universidad",
        "proyectos",
        "iglesia",
        "personal",
    ]
    found = areas.find_area_by_name(conn, "  UNIVERSIDAD ")
    assert found is not None and found.name == "universidad"


def test_crear_area_nueva_aparece_en_la_lista(conn, clock):
    created = areas.create_area(conn, "  Salud  ", "Ejercicio, citas médicas y hábitos.", clock)
    assert created.name == "Salud" and not created.archived
    assert created.id in [a.id for a in areas.list_areas(conn)]


@pytest.mark.parametrize(
    ("name", "description"),
    [("", "algo"), ("   ", "algo"), ("x" * 41, "algo"), ("Iglesia", "repetida")],
)
def test_area_invalida_se_rechaza(conn, clock, name, description):
    with pytest.raises(areas.AreaError):
        areas.create_area(conn, name, description, clock)


def test_archivar_area_no_la_borra(conn):
    target = areas.find_area_by_name(conn, "personal")
    areas.archive_area(conn, target.id)
    assert "personal" not in [a.name for a in areas.list_areas(conn)]
    assert "personal" in [a.name for a in areas.list_areas(conn, include_archived=True)]
    assert areas.get_area(conn, target.id).archived is True


# --- Tareas --------------------------------------------------------------------------------


def test_crear_tarea_guarda_utc_y_texto_original(conn, clock):
    due = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)
    task = tasks.create_task(
        conn, "entregar proyecto", clock, due_at_utc=due, source_text="Entregar proyecto el viernes"
    )
    assert task.status == "open" and task.area_id is None
    assert task.due_at_utc == "2026-10-09T23:00:00+00:00"
    assert task.created_at == to_utc_iso(clock()) == task.updated_at
    assert task.source_text == "Entregar proyecto el viernes"


def test_hacer_y_descartar_son_soft_delete(conn, clock):
    done = tasks.create_task(conn, "a", clock)
    dropped = tasks.create_task(conn, "b", clock)
    clock.advance(minutes=5)
    assert tasks.mark_done(conn, done.id, clock) is True
    assert tasks.drop_task(conn, dropped.id, clock) is True
    assert tasks.get_task(conn, done.id).status == "done"
    assert tasks.get_task(conn, dropped.id).status == "dropped"
    assert tasks.get_task(conn, done.id).closed_at == to_utc_iso(clock())
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2  # nada se borró
    assert tasks.list_open(conn) == []


def test_cerrar_dos_veces_no_hace_nada_la_segunda(conn, clock):
    task = tasks.create_task(conn, "a", clock)
    assert tasks.mark_done(conn, task.id, clock) is True
    assert tasks.drop_task(conn, task.id, clock) is False  # ya estaba cerrada
    assert tasks.get_task(conn, task.id).status == "done"
    assert tasks.mark_done(conn, 999, clock) is False


def test_posponer_deja_de_estar_abierta(conn, clock):
    task = tasks.create_task(conn, "a", clock)
    until = clock() + timedelta(days=1)
    assert tasks.postpone_task(conn, task.id, until, clock) is True
    stored = tasks.get_task(conn, task.id)
    assert stored.status == "postponed" and stored.postponed_until_utc == to_utc_iso(until)
    assert tasks.list_open(conn) == []


def test_list_open_ordena_por_fecha_y_filtra_por_area(conn, clock):
    uni = areas.find_area_by_name(conn, "universidad").id
    no_date = tasks.create_task(conn, "sin fecha", clock, area_id=uni)
    later = tasks.create_task(conn, "después", clock, due_at_utc=clock() + timedelta(days=5))
    soon = tasks.create_task(
        conn, "pronto", clock, area_id=uni, due_at_utc=clock() + timedelta(days=1)
    )
    assert [t.id for t in tasks.list_open(conn)] == [soon.id, later.id, no_date.id]
    assert [t.id for t in tasks.list_open(conn, area_id=uni)] == [soon.id, no_date.id]


def test_list_due_before_incluye_vencidas_y_excluye_futuras(conn, clock):
    overdue = tasks.create_task(conn, "vencida", clock, due_at_utc=clock() - timedelta(days=2))
    today = tasks.create_task(conn, "hoy", clock, due_at_utc=clock() + timedelta(hours=1))
    tasks.create_task(conn, "mañana", clock, due_at_utc=clock() + timedelta(days=1))
    tasks.create_task(conn, "sin fecha", clock)
    closed = tasks.create_task(conn, "hecha", clock, due_at_utc=clock() - timedelta(days=1))
    tasks.mark_done(conn, closed.id, clock)
    _, end_of_today = local_day_bounds(clock(), TZ)
    assert [t.id for t in tasks.list_due_before(conn, end_of_today)] == [overdue.id, today.id]


def test_local_day_bounds_usa_el_dia_local():
    # 03:00 UTC del domingo 4 sigue siendo sábado 3 a las 21:00 en México.
    start, end = local_day_bounds(datetime(2026, 10, 4, 3, 0, tzinfo=UTC), TZ)
    assert start == datetime(2026, 10, 3, 6, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 4, 6, 0, tzinfo=UTC)


def test_local_day_bounds_dia_de_cambio_de_horario():
    # 8 de marzo de 2026 en Nueva York dura 23 horas (se adelantan los relojes).
    start, end = local_day_bounds(datetime(2026, 3, 8, 15, 0, tzinfo=UTC), "America/New_York")
    assert end - start == timedelta(hours=23)


# --- Notas ---------------------------------------------------------------------------------


def test_notas_recientes_primero_y_archivar_no_borra(conn, clock):
    first = notes.create_note(conn, "primera", clock)
    clock.advance(minutes=1)
    second = notes.create_note(conn, "segunda", clock, area_id=1)
    assert [n.id for n in notes.list_notes(conn)] == [second.id, first.id]
    assert [n.id for n in notes.list_notes(conn, area_id=1)] == [second.id]
    notes.archive_note(conn, first.id)
    assert [n.id for n in notes.list_notes(conn)] == [second.id]
    assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 2


def test_notas_limite_de_resultados(conn, clock):
    for i in range(25):
        clock.advance(seconds=1)
        notes.create_note(conn, f"nota {i}", clock)
    assert len(notes.list_notes(conn)) == 20


# --- Ajuste meridiem_ask_range (migración 003) ---------------------------------------------


def test_migracion_003_siembra_meridiem_ask_range(conn):
    from asistente.core.settings import get_meridiem_ask_range

    versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert versions[:3] == [1, 2, 3]
    assert get_meridiem_ask_range(conn) == (5, 11)


@pytest.mark.parametrize(
    ("raw", "expected"), [("6-10", (6, 10)), ("1-11", (1, 11)), ("7-7", (7, 7))]
)
def test_meridiem_ask_range_se_lee_del_ajuste(conn, raw, expected):
    from asistente.core.settings import get_meridiem_ask_range

    conn.execute("UPDATE settings SET value = ? WHERE key = 'meridiem_ask_range'", (raw,))
    assert get_meridiem_ask_range(conn) == expected


@pytest.mark.parametrize("raw", ["", "5", "5-", "a-b", "0-5", "5-12", "9-5", "5-11-3"])
def test_meridiem_ask_range_invalido_falla_con_mensaje_claro(conn, raw):
    from asistente.core.settings import get_meridiem_ask_range

    conn.execute("UPDATE settings SET value = ? WHERE key = 'meridiem_ask_range'", (raw,))
    with pytest.raises(ValueError, match="meridiem_ask_range"):
        get_meridiem_ask_range(conn)
