"""Parser de fechas en español: tablas con reloj fijo.

Reloj: sábado 2026-10-03 15:30 en México (UTC-6, sin horario de verano).
`default_morning_time` = 09:00. Rango de horas sin am/pm que se preguntan: 5-11.
"""

from datetime import UTC, datetime, time

import pytest

from asistente.parsing.dates import WEEKDAYS, format_when, parse_when
from asistente.timeutil import local_to_utc

TZ = "America/Mexico_City"
NOW = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)  # = sábado 15:30 local
DEFAULT_MORNING = time(9, 0)


def clock() -> datetime:
    return NOW


def parse(text: str, now: datetime = NOW, tz: str = TZ, **kwargs):
    return parse_when(text, lambda: now, tz, DEFAULT_MORNING, **kwargs)


def utc(local_text: str, tz: str = TZ) -> datetime:
    """'2026-10-04 08:00' (hora local) -> datetime UTC."""
    return local_to_utc(datetime.strptime(local_text, "%Y-%m-%d %H:%M"), tz)


# (frase, fecha local esperada, ¿trae hora?, título esperado o None si no se comprueba)
OK_CASES = [
    ("mañana a las 2 menos cuarto", "2026-10-04 13:45", True, None),  # regla 3: "menos cuarto"
    ("mañana 8am", "2026-10-04 08:00", True, None),
    ("mañana a las 8 am", "2026-10-04 08:00", True, None),
    ("mañana a las 8 de la mañana", "2026-10-04 08:00", True, None),
    (
        "recordar mañana 8am llevar tarea de cálculo",
        "2026-10-04 08:00",
        True,
        "llevar tarea de cálculo",
    ),
    (
        "llevar tarea de cálculo mañana a las 8 am",
        "2026-10-04 08:00",
        True,
        "llevar tarea de cálculo",
    ),
    ("el viernes a las 5 pm", "2026-10-09 17:00", True, None),
    ("viernes a las 5 pm", "2026-10-09 17:00", True, None),
    ("viernes 5pm", "2026-10-09 17:00", True, None),
    ("el domingo a las 8 pm", "2026-10-04 20:00", True, None),
    ("el domingo 20:00", "2026-10-04 20:00", True, None),  # regla 5: sin "el" ahora se pregunta
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
    ("mañana a las 3 y media", "2026-10-04 15:30", True, None),  # 1-4 sin marcador = tarde
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

# --- Regla de la hora sin am/pm (docs/PLAN_FASE1.md, regla 3) ---------------------------------
# Sin marcador: 12 = mediodía; 1-4 = tarde (inferido); 5-11 = PREGUNTA con las dos lecturas.

# "mañana a las H" (y `H:30` suelto, que se comporta igual): hora, lectura, ¿inferida?
BARE_HOUR_OK = [
    (1, "13:00", True),
    (2, "14:00", True),
    (3, "15:00", True),
    (4, "16:00", True),
    (12, "12:00", False),
]
BARE_HOUR_ASK = [5, 6, 7, 8, 9, 10, 11]


@pytest.mark.parametrize(("hour", "reading", "inferred"), BARE_HOUR_OK)
@pytest.mark.parametrize("form", ["mañana a las {h}", "mañana {h}:30", "mañana a las {h}:30"])
def test_hora_sin_marcador_se_asume(hour, reading, inferred, form):
    minute = "30" if ":30" in form else "00"
    text = form.format(h=hour)
    result = parse(text)
    assert result.status == "ok", (text, result)
    assert result.when_utc == utc(f"2026-10-04 {reading.split(':')[0]}:{minute}"), (text, result)
    assert result.meridiem_inferred is inferred


@pytest.mark.parametrize("hour", BARE_HOUR_ASK)
@pytest.mark.parametrize("form", ["mañana a las {h}", "mañana {h}:30", "mañana a las {h}:30"])
def test_hora_5_a_11_sin_marcador_pregunta_con_las_dos_lecturas(hour, form):
    text = form.format(h=hour)
    minute = "30" if ":30" in form else "00"
    result = parse(text)
    assert (result.status, result.reason) == ("ask", "ambiguous_meridiem"), (text, result)
    assert result.when_utc is None
    assert list(result.candidates) == [
        utc(f"2026-10-04 {hour:02d}:{minute}"),
        utc(f"2026-10-04 {hour + 12:02d}:{minute}"),
    ]


@pytest.mark.parametrize("hour", range(1, 12))
def test_con_am_se_respeta(hour):
    result = parse(f"mañana a las {hour} am")
    assert result.when_utc == utc(f"2026-10-04 {hour:02d}:00") and not result.meridiem_inferred


@pytest.mark.parametrize("hour", range(1, 12))
def test_con_pm_se_respeta(hour):
    result = parse(f"mañana a las {hour} pm")
    assert result.when_utc == utc(f"2026-10-04 {hour + 12:02d}:00")
    assert not result.meridiem_inferred


@pytest.mark.parametrize(
    ("text", "local"),
    [
        ("mañana a las 12 pm", "2026-10-04 12:00"),
        ("mañana 6:30 pm", "2026-10-04 18:30"),
        ("mañana 6:30 de la tarde", "2026-10-04 18:30"),
        ("mañana a las 6 de la mañana", "2026-10-04 06:00"),
        ("mañana 9 de la noche", "2026-10-04 21:00"),
        ("mañana a las 13", "2026-10-04 13:00"),
        ("mañana a las 18", "2026-10-04 18:00"),
        ("mañana a las 23", "2026-10-04 23:00"),
        ("mañana a las 0", "2026-10-04 00:00"),
        ("mañana 06:30", "2026-10-04 06:30"),  # cero inicial = 24 h: se respeta, no se pregunta
        ("mañana 9:30 pm", "2026-10-04 21:30"),
    ],
)
def test_con_marcador_o_24_horas_nunca_se_pregunta(text, local):
    result = parse(text)
    assert result.status == "ok", (text, result)
    assert result.when_utc == utc(local)
    assert result.meridiem_inferred is False


def test_12_am_y_12_de_la_noche_siguen_preguntando():
    for text in ("mañana a las 12 am", "mañana 12 de la noche", "mañana 12:30 am"):
        result = parse(text)
        assert (result.status, result.reason) == ("ask", "ambiguous_time"), text
        # Regla 3 + interpretación 5: las dos medianoches futuras (la de mañana y la siguiente)
        minute = "30" if "12:30" in text else "00"
        assert list(result.candidates) == [
            utc(f"2026-10-04 00:{minute}"),
            utc(f"2026-10-05 00:{minute}"),
        ], text


def test_h_mm_suelto_sin_dia_no_es_hora():
    assert parse("leer Juan 3:16").status == "none"
    assert parse("Romanos 8:28").status == "none"  # versículo: ni pregunta ni inventa


def test_la_lectura_pasada_se_descarta_de_las_opciones():
    # Hoy sábado a las 15:30: "a las 8" -> 8 am ya pasó, solo queda 8 pm.
    result = parse("hoy a las 8")
    assert (result.status, result.reason) == ("ask", "ambiguous_meridiem")
    assert list(result.candidates) == [utc("2026-10-03 20:00")]


def test_si_las_dos_lecturas_ya_pasaron_se_pregunta_por_el_pasado():
    late = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)  # sábado 23:00 local
    result = parse("hoy a las 9", late)
    assert (result.status, result.reason) == ("ask", "past")
    assert list(result.candidates) == [utc("2026-10-04 09:00")]


def test_hora_asumida_que_ya_paso_hoy_pregunta_con_alternativa():
    result = parse("hoy a las 3")  # 3 -> 3 pm (15:00), ya pasó a las 15:30
    assert (result.status, result.reason) == ("ask", "past")
    assert list(result.candidates) == [utc("2026-10-04 15:00")]


def test_el_rango_a_preguntar_es_un_parametro():
    # Rango 7-11: la hora 6 deja de preguntarse y se asume por debajo del rango (tarde).
    narrow = parse("mañana a las 6", meridiem_ask_range=(7, 11))
    assert narrow.when_utc == utc("2026-10-04 18:00") and narrow.meridiem_inferred
    assert parse("mañana a las 7", meridiem_ask_range=(7, 11)).reason == "ambiguous_meridiem"
    # Rango 1-4: las horas por encima del rango (5-11) se asumen de la mañana.
    wide = parse("mañana a las 8", meridiem_ask_range=(1, 4))
    assert wide.when_utc == utc("2026-10-04 08:00") and wide.meridiem_inferred
    assert parse("mañana a las 3", meridiem_ask_range=(1, 4)).reason == "ambiguous_meridiem"
    # Rango completo: todo se pregunta salvo 12.
    assert parse("mañana a las 1", meridiem_ask_range=(1, 11)).reason == "ambiguous_meridiem"
    assert parse("mañana a las 12", meridiem_ask_range=(1, 11)).status == "ok"


@pytest.mark.parametrize("bad_range", [(0, 5), (5, 12), (8, 5), (-1, 4)])
def test_rango_invalido_se_rechaza(bad_range):
    with pytest.raises(ValueError):
        parse("mañana a las 8", meridiem_ask_range=bad_range)


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
    ("mañana a las 12 de la noche", "ambiguous_time", ["2026-10-04 00:00", "2026-10-05 00:00"]),
    ("mañana a las 12 am", "ambiguous_time", ["2026-10-04 00:00", "2026-10-05 00:00"]),
    ("mañana a las 1 de la noche", "ambiguous_time", []),
    ("mañana por la mañana", "unrecognized_time", []),
    ("mañana por la tarde", "unrecognized_time", []),
    (
        "mañana medianoche",
        "ambiguous_time",
        ["2026-10-04 00:00", "2026-10-05 00:00"],
    ),  # regla 3: medianoche
    ("llamar a Domingo", "name_or_day", []),  # regla 5 (antes: sin fecha)
    ("regalo para Domingo", "name_or_day", []),  # regla 5 (antes: sin fecha)
    ("domingo 20:00", "name_or_day", []),  # regla 5 (antes: domingo 20:00)
    ("mañana a las 25", "invalid_time", []),
    ("mañana a las 15 pm", "invalid_time", []),
    ("mañana a las 0 am", "invalid_time", []),
    (
        "llevar tarea de cálculo mañana a las 8",
        "ambiguous_meridiem",
        ["2026-10-04 08:00", "2026-10-04 20:00"],
    ),
    ("viernes a las 5", "ambiguous_meridiem", ["2026-10-09 05:00", "2026-10-09 17:00"]),
    ("mañana a las 8 y media", "ambiguous_meridiem", ["2026-10-04 08:30", "2026-10-04 20:30"]),
    ("mañana a las 5 y cuarto", "ambiguous_meridiem", ["2026-10-04 05:15", "2026-10-04 17:15"]),
    ("mañana 8:30", "ambiguous_meridiem", ["2026-10-04 08:30", "2026-10-04 20:30"]),
    ("mañana 6:30", "ambiguous_meridiem", ["2026-10-04 06:30", "2026-10-04 18:30"]),
    ("a las 9", "ambiguous_meridiem", ["2026-10-03 21:00"]),  # 9 am de hoy ya pasó
    ("el sábado a las 5", "same_weekday", []),  # primero el día; la hora se pregunta después
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
    "leer Juan 3:16",
    "estudiar capítulo 5 de la biblia",
    "tengo 5 amigos",
    "ir a la iglesia",
    "me quedan 30 páginas",
    "pagar 100 pesos",
    "sábados de limpieza",
    "5 de 10 completadas",
    "recordar mi contraseña",
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
    for _, _, candidates in ASK_CASES:
        assert all(utc(c) > NOW for c in candidates)


def test_el_titulo_conserva_el_texto_cuando_no_hay_fecha():
    assert parse("  comprar   leche ").title == "comprar leche"


# --- "Domingo": día de la semana frente a nombre propio ---------------------------------------
# Solo "domingo" puede ser un nombre (los otros seis días siguen siendo fecha). Regla 5: sin
# determinante (el, este, esta, próximo, que viene, para el) SE PREGUNTA con cualquier
# capitalización y en cualquier posición; con determinante es fecha.

# Para cada día: a qué fecha cae (el reloj es sábado 3) y 17:00 como hora. El sábado es "hoy".
_DAY_DATES = {
    "lunes": "2026-10-05",
    "martes": "2026-10-06",
    "miercoles": "2026-10-07",
    "jueves": "2026-10-08",
    "viernes": "2026-10-09",
    "sabado": None,  # es hoy: "el sábado" pregunta (same_weekday)
    "domingo": "2026-10-04",
}
_DAY_SPELLINGS = {
    "lunes": "lunes",
    "martes": "martes",
    "miercoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sabado": "sábado",
    "domingo": "domingo",
}
_CAPS = {"minúscula": str.lower, "Mayúscula": str.capitalize, "MAYÚSCULAS": str.upper}
# (nombre del contexto, plantilla, ¿lleva artículo/determinante?, ¿el día va al inicio del texto?)
_CONTEXTS = [
    ("con artículo", "reunión el {d} a las 5 pm", True, False),
    ("sin artículo, al inicio", "{d} a las 5 pm", False, True),
    ("sin artículo, a mitad", "reunión {d} a las 5 pm", False, False),
    ("tras 'a'", "llamar a {d} a las 5 pm", False, False),
    ("tras 'con'", "salir con {d} a las 5 pm", False, False),
]


def _expected_for(day: str, caps: str, has_determiner: bool, at_start: bool):
    is_name = day == "domingo" and not has_determiner  # regla 5: sin importar mayúsculas ni lugar
    if is_name:
        return ("ask", "name_or_day", None)
    if day == "sabado":
        return ("ask", "same_weekday", None)
    return ("ok", None, f"{_DAY_DATES[day]} 17:00")


_MATRIX = [
    pytest.param(day, caps_name, context, id=f"{day}-{caps_name}-{context[0]}")
    for day in WEEKDAYS
    for caps_name in _CAPS
    for context in _CONTEXTS
]


@pytest.mark.parametrize(("day", "caps_name", "context"), _MATRIX)
def test_dias_de_la_semana_por_capitalizacion_y_contexto(day, caps_name, context):
    _, template, has_determiner, at_start = context
    text = template.format(d=_CAPS[caps_name](_DAY_SPELLINGS[day]))
    status, reason, local = _expected_for(day, caps_name, has_determiner, at_start)
    result = parse(text)
    assert (result.status, result.reason) == (status, reason), (text, result)
    if status == "ok":
        assert result.when_utc == utc(local), (text, result)
    else:
        assert result.when_utc is None  # nunca se asume "hoy"


def test_la_matriz_cubre_21_combinaciones_por_contexto():
    assert len(_MATRIX) == 7 * 3 * 5


@pytest.mark.parametrize(
    "text",
    [
        "reunión Domingo que viene a las 5 pm",
        "reunión este Domingo a las 5 pm",
        "reunión esta Domingo a las 5 pm",
        "reunión próximo Domingo a las 5 pm",
        "reunión el próximo DOMINGO a las 5 pm",
        "reunión EL DOMINGO a las 5 pm",
        "reunión ESTE DOMINGO a las 5 pm",
        "REUNIÓN EL DOMINGO A LAS 5 PM",  # todo en mayúsculas pero con determinante: fecha
        "reunión para el domingo a las 5 pm",
    ],
)
def test_domingo_con_determinante_o_todo_en_mayusculas_es_fecha(text):
    result = parse(text)
    assert result.status == "ok", (text, result)
    assert result.when_utc == utc("2026-10-04 17:00")


def test_frases_de_domingo_del_usuario():
    assert parse("reunión el Domingo a las 5 pm").when_utc == utc("2026-10-04 17:00")
    llamar = parse("llamar a Domingo")  # regla 5: sin determinante se pregunta, aunque no haya hora
    assert (llamar.status, llamar.reason, llamar.title) == (
        "ask",
        "name_or_day",
        "llamar a Domingo",
    )
    ambiguous = parse("llamar a Domingo a las 5")
    assert (ambiguous.status, ambiguous.reason) == ("ask", "name_or_day")
    assert ambiguous.title == "llamar a Domingo"


def test_con_un_nombre_domingo_y_otro_dia_la_fecha_es_la_del_otro_dia():
    result = parse("llamar a Domingo mañana a las 5 pm")
    assert result.status == "ok" and result.when_utc == utc("2026-10-04 17:00")


@pytest.mark.parametrize(
    "text",
    ["Domingo", "Domingo a las 5 pm", "domingo a las 5 pm", "DOMINGO A LAS 5 PM", "para domingo"],
)
def test_domingo_sin_determinante_pregunta_tambien_al_inicio(text):
    result = parse(text)  # regla 5: al inicio y en mayúsculas ya no se asume que es el día
    assert (result.status, result.reason) == ("ask", "name_or_day"), text
    assert result.when_utc is None


# --- Verbo inicial del título -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("recordar mañana 8am llevar tarea de cálculo", "llevar tarea de cálculo"),
        ("recuérdame mañana a las 8 am llamar a mamá", "llamar a mamá"),
        ("Recuérdame mañana 8am llamar a mamá", "llamar a mamá"),
        ("recuérdame que mañana a las 8 am llame a mamá", "llame a mamá"),
        ("recordarme de llamar mañana 8am", "llamar"),
        ("llamar a mamá mañana 8am", "llamar a mamá"),
        ("recordar mañana", "recordar"),  # sola, no se quita
        ("mañana a las 8 am recordar pagar", "pagar"),  # tras quitar la fecha, queda al inicio
        ("pagar y recordar mañana 8am", "pagar y recordar"),  # a mitad de frase no se toca
    ],
)
def test_se_quita_el_verbo_inicial_de_recordatorio(text, title):
    assert parse(text).title == title


def test_sin_fecha_el_titulo_no_se_toca():
    assert parse("recordar mi contraseña").title == "recordar mi contraseña"


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
    assert parse("esta Viernes a las 5 pm", friday).when_utc == utc("2026-10-09 17:00")


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
