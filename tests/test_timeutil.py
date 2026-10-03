from datetime import UTC, datetime

import pytest

from asistente import timeutil


def test_now_es_utc_con_zona():
    assert timeutil.now().tzinfo is UTC


def test_ida_y_vuelta_iso():
    moment = datetime(2026, 10, 3, 15, 30, tzinfo=UTC)
    text = timeutil.to_utc_iso(moment)
    assert text == "2026-10-03T15:30:00+00:00"
    assert timeutil.from_utc_iso(text) == moment


def test_to_utc_iso_rechaza_datetime_sin_zona():
    with pytest.raises(ValueError):
        timeutil.to_utc_iso(datetime(2026, 10, 3, 15, 30))


def test_to_local_solo_cambia_la_presentacion():
    moment = datetime(2026, 1, 15, 18, 0, tzinfo=UTC)
    local = timeutil.to_local(moment, "America/Mexico_City")  # UTC-6 en enero
    assert local.hour == 12
    assert local == moment


def test_local_a_utc_respeta_el_horario_de_verano():
    # Madrid: UTC+1 en invierno, UTC+2 en verano.
    invierno = timeutil.local_to_utc(datetime(2026, 1, 15, 9, 0), "Europe/Madrid")
    verano = timeutil.local_to_utc(datetime(2026, 7, 15, 9, 0), "Europe/Madrid")
    assert invierno.hour == 8
    assert verano.hour == 7


def test_reloj_inyectable():
    fixed = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

    def uses_clock(clock: timeutil.Clock = timeutil.now) -> datetime:
        return clock()

    assert uses_clock(lambda: fixed) == fixed
