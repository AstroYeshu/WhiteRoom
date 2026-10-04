"""Bloque 7b (núcleo): áreas con descripción opcional, nombre único y conteo de la bandeja."""

import pytest

from asistente.core import areas, tasks


def test_una_area_puede_crearse_sin_descripcion(conn, clock):
    created = areas.create_area(conn, "Salud", "", clock)
    assert created.description == ""
    assert areas.find_area_by_name(conn, "salud").id == created.id


def test_la_descripcion_en_blanco_se_guarda_vacia(conn, clock):
    assert areas.create_area(conn, "Salud", "   ", clock).description == ""


@pytest.mark.parametrize(
    "duplicate", ["universidad", "UNIVERSIDAD", "  Universidad ", "Universidád", "universidàd"]
)
def test_el_nombre_es_unico_sin_distinguir_mayusculas_ni_acentos(conn, clock, duplicate):
    with pytest.raises(areas.AreaError, match="Ya existe"):
        areas.create_area(conn, duplicate, "otra", clock)


def test_el_acento_cuenta_igual_en_las_areas_nuevas(conn, clock):
    areas.create_area(conn, "Música", "", clock)
    with pytest.raises(areas.AreaError, match="Ya existe"):
        areas.create_area(conn, "MUSICA", "", clock)


def test_un_area_archivada_tambien_reserva_su_nombre(conn, clock):
    archived = areas.create_area(conn, "Viajes", "", clock)
    areas.archive_area(conn, archived.id)
    with pytest.raises(areas.AreaError, match="Ya existe"):
        areas.create_area(conn, "viajes", "", clock)


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_un_nombre_invalido_se_rechaza(conn, clock, name):
    with pytest.raises(areas.AreaError):
        areas.create_area(conn, name, "algo", clock)


def test_contar_la_bandeja_solo_cuenta_abiertas_sin_area(conn, clock):
    area = areas.find_area_by_name(conn, "personal")
    tasks.create_task(conn, "uno", clock)
    tasks.create_task(conn, "dos", clock)
    tasks.create_task(conn, "con área", clock, area_id=area.id)
    done = tasks.create_task(conn, "hecha", clock)
    tasks.mark_done(conn, done.id, clock)
    assert tasks.count_inbox(conn) == 2
