"""Repeticiones: lista cerrada de expresiones y cálculo de la siguiente ocurrencia sin deriva."""

from datetime import UTC, datetime, time, timedelta

import pytest

from asistente.parsing.recurrence import next_occurrence, parse_recurrence
from asistente.timeutil import local_to_utc

TZ = "America/Mexico_City"
NOW = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)  # sábado 15:30 local


def parse(text: str, now: datetime = NOW):
    return parse_recurrence(text, lambda: now, TZ, time(9, 0))


def utc(local_text: str, tz: str = TZ) -> datetime:
    return local_to_utc(datetime.strptime(local_text, "%Y-%m-%d %H:%M"), tz)


@pytest.mark.parametrize(
    ("text", "rrule", "first", "has_time", "title"),
    [
        (
            "todos los días a las 8 am tomar vitaminas",
            "FREQ=DAILY",
            "2026-10-04 08:00",
            True,
            "tomar vitaminas",
        ),
        (
            "todos los días a las 2 menos cuarto",
            "FREQ=DAILY",
            "2026-10-04 13:45",
            True,
            "",
        ),  # regla 3
        ("todos los días", "FREQ=DAILY", "2026-10-04 09:00", False, ""),  # 09:00 de hoy ya pasó
        ("todos los días 8pm leer", "FREQ=DAILY", "2026-10-03 20:00", True, "leer"),
        ("cada domingo 8pm", "FREQ=WEEKLY;BYDAY=SU", "2026-10-04 20:00", True, ""),
        (
            "cada viernes a las 5 pm entregar reporte",
            "FREQ=WEEKLY;BYDAY=FR",
            "2026-10-09 17:00",
            True,
            "entregar reporte",
        ),
        ("cada sábado a las 6 pm", "FREQ=WEEKLY;BYDAY=SA", "2026-10-03 18:00", True, ""),  # hoy aún
        (
            "cada sábado a las 10 am",
            "FREQ=WEEKLY;BYDAY=SA",
            "2026-10-10 10:00",
            True,
            "",
        ),  # hoy ya pasó
        ("cada lunes", "FREQ=WEEKLY;BYDAY=MO", "2026-10-05 09:00", False, ""),
        (
            "de lunes a viernes a las 7 am gimnasio",
            "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
            "2026-10-05 07:00",
            True,
            "gimnasio",
        ),
        ("de lunes a viernes", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "2026-10-05 09:00", False, ""),
        ("cada martes 8:30 am", "FREQ=WEEKLY;BYDAY=TU", "2026-10-06 08:30", True, ""),
    ],
)
def test_expresiones_reconocidas(text, rrule, first, has_time, title):
    result = parse(text)
    assert result.status == "ok", (text, result)
    assert result.rrule == rrule
    assert result.first_at_utc == utc(first)
    assert result.has_time is has_time
    assert result.title == title


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("cada lunes y cada martes", "two_dates"),
        ("todos los días a las 8 y a las 5", "two_dates"),
        ("todos los días mañana", "two_dates"),
        ("cada lunes el 15 de octubre", "two_dates"),
        ("cada martes 8:30", "ambiguous_meridiem"),
        ("todos los días a las 8", "ambiguous_meridiem"),
        ("de lunes a viernes a las 6", "ambiguous_meridiem"),
        ("todos los días a las 12 de la noche", "ambiguous_time"),
    ],
)
def test_ante_la_duda_pregunta(text, reason):
    result = parse(text)
    assert (result.status, result.reason) == ("ask", reason)
    assert result.first_at_utc is None


@pytest.mark.parametrize(
    "text",
    ["comprar leche", "cada quince días", "los lunes", "mañana a las 8", "diario", "cada semana"],
)
def test_fuera_de_la_lista_cerrada_no_se_interpreta(text):
    assert parse(text).status == "none"


# --- next_occurrence: sin deriva y con horario de verano -------------------------------------


def test_semanal_sin_deriva_aunque_se_dispare_tarde():
    scheduled = utc("2026-10-04 20:00")  # domingo 20:00
    current = scheduled
    for week in range(1, 11):
        late = current + timedelta(minutes=3, seconds=17)  # el aviso salió con retraso
        current = next_occurrence("FREQ=WEEKLY;BYDAY=SU", current, late, TZ)
        assert current == scheduled + timedelta(weeks=week)


def test_diario_sin_deriva():
    scheduled = utc("2026-10-04 08:00")
    nxt = next_occurrence("FREQ=DAILY", scheduled, scheduled + timedelta(minutes=45), TZ)
    assert nxt == scheduled + timedelta(days=1)


def test_tras_una_caida_larga_salta_a_la_primera_ocurrencia_futura():
    scheduled = utc("2026-10-04 20:00")  # domingo
    now = scheduled + timedelta(weeks=3, hours=2)
    assert next_occurrence("FREQ=WEEKLY;BYDAY=SU", scheduled, now, TZ) == scheduled + timedelta(
        weeks=4
    )


def test_horario_de_verano_mantiene_la_hora_local():
    ny = "America/New_York"
    before = utc("2026-03-01 20:00", ny)  # domingo, EST (UTC-5)
    nxt = next_occurrence("FREQ=WEEKLY;BYDAY=SU", before, before, ny)
    assert nxt == utc("2026-03-08 20:00", ny)  # el 8 ya es EDT (UTC-4)
    assert nxt == datetime(2026, 3, 9, 0, 0, tzinfo=UTC)  # el UTC se movió una hora
    assert nxt - before == timedelta(days=7) - timedelta(hours=1)


def test_serie_terminada_devuelve_none():
    scheduled = utc("2026-10-04 08:00")
    assert next_occurrence("FREQ=DAILY;COUNT=1", scheduled, scheduled, TZ) is None


def test_hora_de_1_a_4_sin_marcador_se_asume_tarde_y_se_marca():
    result = parse("todos los días a las 3 tomar agua")
    assert result.status == "ok" and result.meridiem_inferred is True
    assert result.first_at_utc == utc("2026-10-04 15:00")  # hoy 15:00 ya pasó
    assert parse("todos los días a las 3 pm").meridiem_inferred is False


def test_el_rango_a_preguntar_tambien_aplica_a_las_repeticiones():
    result = parse_recurrence("todos los días a las 6", lambda: NOW, TZ, time(9, 0), (7, 11))
    assert result.status == "ok" and result.meridiem_inferred is True
    assert result.first_at_utc == utc("2026-10-03 18:00")


def test_se_quita_el_verbo_inicial_del_titulo():
    result = parse("recuérdame todos los días a las 8 am tomar vitaminas")
    assert result.status == "ok" and result.title == "tomar vitaminas"
