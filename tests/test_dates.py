"""Parser de fechas en español: tablas con reloj fijo.

Reloj: sábado 2026-10-03 15:30 en México (UTC-6, sin horario de verano).
`default_morning_time` = 09:00.
"""

from datetime import UTC, datetime, time

import pytest

from asistente.parsing.dates import format_when, parse_when
from asistente.timeutil import local_to_utc

TZ = "America/Mexico_City"
NOW = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)  # = sábado 15:30 local
DEFAULT_MORNING = time(9, 0)


def clock() -> datetime:
    return NOW


def parse(text: str, now: datetime = NOW, tz: str = TZ):
    return parse_when(text, lambda: now, tz, DEFAULT_MORNING)


def utc(local_text: str, tz: str = TZ) -> datetime:
    """'2026-10-04 08:00' (hora local) -> datetime UTC."""
    return local_to_utc(datetime.strptime(local_text, "%Y-%m-%d %H:%M"), tz)


# (frase, fecha local esperada, ¿trae hora?, título esperado o None si no se comprueba)
OK_CASES = [
    ("mañana 8am", "2026-10-04 08:00", True, None),
    ("mañana a las 8 am", "2026-10-04 08:00", True, None),
    ("mañana a las 8 de la mañana", "2026-10-04 08:00", True, None),
    (
        "recordar mañana 8am llevar tarea de cálculo",
        "2026-10-04 08:00",
        True,
        "recordar llevar tarea de cálculo",
    ),
    ("llevar tarea de cálculo mañana a las 8", "2026-10-04 08:00", True, "llevar tarea de cálculo"),
    ("el viernes a las 5 pm", "2026-10-09 17:00", True, None),
    ("viernes a las 5", "2026-10-09 17:00", True, None),
    ("viernes 5pm", "2026-10-09 17:00", True, None),
    ("el domingo a las 8 pm", "2026-10-04 20:00", True, None),
    ("domingo 20:00", "2026-10-04 20:00", True, None),
    ("pasado mañana", "2026-10-05 09:00", False, None),
    ("pasado mañana a las 9 am", "2026-10-05 09:00", True, None),
    ("hoy a las 6 pm llamar a mamá", "2026-10-03 18:00", True, "llamar a mamá"),
    ("hoy 6 pm", "2026-10-03 18:00", True, None),
    ("llamar a Juan a las 18:30", "2026-10-03 18:30", True, "llamar a Juan"),
    ("el 15 de octubre pagar la renta", "2026-10-15 09:00", False, "pagar la renta"),
    ("29 de febrero", "2028-02-29 09:00", False, None),
    ("el 1 de enero", "2027-01-01 09:00", False, None),  # sin año = siguiente ocurrencia
    ("el 5 de diciembre de 2026 a las 4 pm", "2026-12-05 16:00", True, None),
    ("el 2 de octubre del 2027", "2027-10-02 09:00", False, None),
    ("el 15/10", "2026-10-15 09:00", False, None),
    ("el 15/10/2026 a las 10 am", "2026-10-15 10:00", True, None),
    ("en 2 horas sacar la ropa", "2026-10-03 17:30", True, "sacar la ropa"),
    ("en 10 minutos", "2026-10-03 15:40", True, None),
    ("en media hora", "2026-10-03 16:00", True, None),
    ("dentro de 3 días", "2026-10-06 09:00", False, None),
    ("en una semana", "2026-10-10 09:00", False, None),
    ("dentro de 2 semanas", "2026-10-17 09:00", False, None),
    ("reunión de jóvenes el domingo", "2026-10-04 09:00", False, "reunión de jóvenes"),
    ("lunes", "2026-10-05 09:00", False, None),
    ("el próximo lunes", "2026-10-05 09:00", False, None),
    ("el lunes que viene", "2026-10-05 09:00", False, None),
    ("este viernes", "2026-10-09 09:00", False, None),
    ("para mañana entregar proyecto", "2026-10-04 09:00", False, "entregar proyecto"),
    ("mañana", "2026-10-04 09:00", False, None),
    ("mañana a las 8 y media", "2026-10-04 08:30", True, None),
    ("mañana a las 5 y cuarto", "2026-10-04 17:15", True, None),
    ("mañana 8:30", "2026-10-04 08:30", True, None),  # H:MM suelto vale si hay día
    ("mañana 18:30", "2026-10-04 18:30", True, None),
    ("mañana 08:00", "2026-10-04 08:00", True, None),
    ("mañana 05:00", "2026-10-04 05:00", True, None),  # cero inicial = 24 h literal
    ("mañana a las 3 de la tarde", "2026-10-04 15:00", True, None),
    ("mañana a las 10 de la noche", "2026-10-04 22:00", True, None),
    ("mañana a las 5 de la madrugada", "2026-10-04 05:00", True, None),
    ("mañana al mediodía", "2026-10-04 12:00", True, None),
    ("mañana a las 12", "2026-10-04 12:00", True, None),
    ("mañana a las 12 pm", "2026-10-04 12:00", True, None),
    ("mañana 5pm", "2026-10-04 17:00", True, None),
    ("mañana 5 p.m.", "2026-10-04 17:00", True, None),
    ("a las 6 pm", "2026-10-03 18:00", True, None),
    ("cena a las 7 pm", "2026-10-03 19:00", True, "cena"),
    ("este sábado a las 6 pm", "2026-10-03 18:00", True, None),
    ("el próximo sábado a las 6 pm", "2026-10-10 18:00", True, None),
    ("el sábado que viene a las 6 pm", "2026-10-10 18:00", True, None),
]

# Regla de la hora sin am/pm: 7-11 = mañana, 12 = mediodía, 1-6 = tarde.
BARE_HOUR_CASES = [
    ("mañana a las 7", "2026-10-04 07:00"),
    ("mañana a las 8", "2026-10-04 08:00"),
    ("mañana a las 11", "2026-10-04 11:00"),
    ("mañana a las 12", "2026-10-04 12:00"),
    ("mañana a las 1", "2026-10-04 13:00"),
    ("mañana a las 3", "2026-10-04 15:00"),
    ("mañana a las 6", "2026-10-04 18:00"),
    ("mañana a las 13", "2026-10-04 13:00"),
    ("mañana a las 23", "2026-10-04 23:00"),
]

# (frase, razón, candidatos locales)
ASK_CASES = [
    ("ayer fui al banco", "past", []),
    ("hoy a las 10 am", "past", ["2026-10-04 10:00"]),
    ("a las 8 am llamar", "past", ["2026-10-04 08:00"]),
    ("hoy llamar a mamá", "past", ["2026-10-04 09:00"]),  # hoy 09:00 ya pasó
    ("el 3 de octubre", "past", ["2027-10-03 09:00"]),
    ("el viernes pasado", "past", []),
    ("el sábado a las 6 pm", "same_weekday", ["2026-10-03 18:00", "2026-10-10 18:00"]),
    ("el sábado a las 10 am", "same_weekday", ["2026-10-10 10:00"]),  # hoy 10 am ya pasó
    ("el sábado", "same_weekday", ["2026-10-10 09:00"]),
    ("mañana a las 8 y el viernes a las 5", "two_dates", []),
    ("mañana y el viernes", "two_dates", []),
    ("mañana a las 8 y a las 5", "two_dates", []),
    ("el 15 de octubre a las 3 pm y el 20 de octubre", "two_dates", []),
    ("dentro de 2 horas mañana", "two_dates", []),
    ("el 31 de abril", "invalid_date", []),
    ("el 30 de febrero", "invalid_date", []),
    ("el 15/13", "invalid_date", []),
    ("en media semana", "invalid_date", []),
    ("mañana a las 12 de la noche", "ambiguous_time", []),
    ("mañana a las 12 am", "ambiguous_time", []),
    ("mañana a las 1 de la noche", "ambiguous_time", []),
    ("mañana por la mañana", "unrecognized_time", []),
    ("mañana por la tarde", "unrecognized_time", []),
    ("mañana medianoche", "unrecognized_time", []),
    ("mañana a las 8 menos cuarto", "unrecognized_time", []),
    ("mañana a las 25", "invalid_time", []),
    ("mañana a las 15 pm", "invalid_time", []),
    ("mañana a las 0 am", "invalid_time", []),
]

# Sin fecha: falsos positivos que NO deben interpretarse como fecha.
NONE_CASES = [
    "comprar leche",
    "estudiar 2 horas",
    "tomar leche de la mañana",
    "la mañana es bonita",
    "esta mañana desayuné tarde",
    "tarea de cálculo 3",
    "comprar 1/2 kilo de arroz",
    "llamar a Domingo",
    "leer Juan 3:16",
    "estudiar capítulo 5 de la biblia",
    "tengo 5 amigos",
    "ir a la iglesia",
    "me quedan 30 páginas",
    "pagar 100 pesos",
    "sábados de limpieza",
    "5 de 10 completadas",
    "",
]


@pytest.mark.parametrize(("text", "local", "has_time", "title"), OK_CASES)
def test_fechas_resueltas(text, local, has_time, title):
    result = parse(text)
    assert result.status == "ok", (text, result)
    assert result.when_utc == utc(local), (text, result)
    assert result.has_time is has_time
    if title is not None:
        assert result.title == title


@pytest.mark.parametrize(("text", "local"), BARE_HOUR_CASES)
def test_hora_sin_am_pm(text, local):
    result = parse(text)
    assert result.status == "ok"
    assert result.when_utc == utc(local)


@pytest.mark.parametrize(("text", "reason", "candidates"), ASK_CASES)
def test_pregunta_en_vez_de_adivinar(text, reason, candidates):
    result = parse(text)
    assert result.status == "ask", (text, result)
    assert result.reason == reason, (text, result)
    assert result.when_utc is None
    assert list(result.candidates) == [utc(c) for c in candidates]


@pytest.mark.parametrize("text", NONE_CASES)
def test_falsos_positivos_no_son_fecha(text):
    result = parse(text)
    assert result.status == "none", (text, result)
    assert result.when_utc is None


def test_nunca_devuelve_una_fecha_en_el_pasado():
    """Barrido: ninguna frase de la tabla `ok` puede quedar en el pasado."""
    for text, *_ in OK_CASES:
        result = parse(text)
        assert result.when_utc is None or result.when_utc > NOW


def test_el_titulo_conserva_el_texto_cuando_no_hay_fecha():
    assert parse("  comprar   leche ").title == "comprar leche"


# --- Casos con el calendario ---------------------------------------------------------------


def test_29_de_febrero_en_dia_bisiesto_cuenta_hoy():
    now = datetime(2028, 2, 29, 12, 0, tzinfo=UTC)  # 06:00 local
    result = parse("el 29 de febrero a las 8 pm", now)
    assert result.when_utc == utc("2028-02-29 20:00")


def test_29_de_febrero_tras_el_dia_bisiesto_va_al_siguiente_bisiesto():
    now = datetime(2028, 3, 1, 12, 0, tzinfo=UTC)
    assert parse("29 de febrero", now).when_utc == utc("2032-02-29 09:00")


def test_el_viernes_siendo_viernes_pregunta_pero_proximo_y_este_no():
    friday = datetime(2026, 10, 9, 16, 0, tzinfo=UTC)  # viernes 10:00 local
    asked = parse("el viernes a las 5 pm", friday)
    assert (asked.status, asked.reason) == ("ask", "same_weekday")
    assert list(asked.candidates) == [utc("2026-10-09 17:00"), utc("2026-10-16 17:00")]
    assert parse("el próximo viernes a las 5 pm", friday).when_utc == utc("2026-10-16 17:00")
    assert parse("este viernes a las 5 pm", friday).when_utc == utc("2026-10-09 17:00")


def test_horario_de_verano_se_respeta():
    # Sábado 7 de marzo de 2026 en Nueva York; el domingo 8 a las 2:00 se adelantan los relojes.
    now = datetime(2026, 3, 7, 17, 0, tzinfo=UTC)
    result = parse("mañana a las 8 am", now, "America/New_York")
    assert result.when_utc == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)  # 8:00 EDT = UTC-4


def test_usa_la_zona_horaria_indicada():
    now = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)  # 23:30 en Madrid
    result = parse("mañana 8am", now, "Europe/Madrid")
    assert result.when_utc == local_to_utc(datetime(2026, 10, 4, 8, 0), "Europe/Madrid")


# --- Presentación --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        ("2026-10-04 08:00", "domingo 4 de octubre, 8:00 am"),
        ("2026-10-09 17:00", "viernes 9 de octubre, 5:00 pm"),
        ("2026-10-05 12:00", "lunes 5 de octubre, 12:00 pm"),
        ("2026-10-05 00:30", "lunes 5 de octubre, 12:30 am"),
        ("2027-01-01 09:00", "viernes 1 de enero de 2027, 9:00 am"),
    ],
)
def test_format_when_muestra_dia_de_la_semana_y_am_pm(local, expected):
    assert format_when(utc(local), TZ, clock) == expected
