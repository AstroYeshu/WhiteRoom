"""Tabla ADVERSARIAL del parser: (frase, reloj local, esperado).

El principio: lo que parece fecha u hora y no se entendió se PREGUNTA; nunca se descarta en
silencio. Reloj por defecto: sábado 2026-10-03 15:30 en México (sin horario de verano).
`default_morning_time` = 09:00.

Esperado (hora local, formato "AAAA-MM-DD HH:MM"):
    ("none",)                         no hay fecha en el texto
    ("ok", local, has_time)           resuelto
    ("ask", razón)                    pregunta (sin comprobar los candidatos)
    ("ask", razón, [local, ...])      pregunta con estos candidatos exactos, en orden
"""

from datetime import datetime, time

import pytest

from asistente.parsing.dates import parse_when
from asistente.timeutil import local_to_utc, to_local

TZ = "America/Mexico_City"
SAT_1530 = "2026-10-03 15:30"
DEFAULT_MORNING = time(9, 0)


def local(text: str, tz: str = TZ) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), tz)


def run(phrase: str, now_local: str = SAT_1530, tz: str = TZ):
    return parse_when(phrase, lambda: local(now_local, tz), tz, DEFAULT_MORNING)


def check(result, expected, phrase: str = "") -> None:
    kind = expected[0]
    assert result.status == kind, (phrase, result)
    if kind == "ok":
        shown = to_local(result.when_utc, TZ).strftime("%Y-%m-%d %H:%M")
        assert shown == expected[1], (phrase, result)
        assert result.has_time is expected[2], (phrase, result)
    elif kind == "ask":
        assert result.reason == expected[1], (phrase, result)
        if len(expected) > 2:
            shown = [to_local(c, TZ).strftime("%Y-%m-%d %H:%M") for c in result.candidates]
            assert shown == expected[2], (phrase, result)
    else:
        assert result.when_utc is None, (phrase, result)


# --- Familia 1: citas bíblicas (regla 1) --------------------------------------------------------
BIBLE = [
    ("leer Juan 3:16 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer Juan 3:16 el domingo", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("Juan 15:13 el domingo", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer Romanos 8:28 el domingo", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer 1 Juan 4:8 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer 2 Corintios 5:17 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer 1Co 13:4 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer Jn 3:16 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer Mt 5:3-12 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer Salmo 23:1 mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("leer Juan 3:16 mañana a las 8 pm", SAT_1530, ("ok", "2026-10-04 20:00", True)),
    ("Mateo 18:20", SAT_1530, ("none",)),
    ("Hechos 20:24", SAT_1530, ("none",)),
    ("Salmos 23:14", SAT_1530, ("none",)),
    ("Salmos 23:4", SAT_1530, ("none",)),
    ("Juan 3:16-18", SAT_1530, ("none",)),
    ("leer Apocalipsis 21:4", SAT_1530, ("none",)),
    # Nombre de persona: solo con "a"/"con" delante y un H:MM válido (ajuste 1 del dueño)
    ("llamar a Juan 3:30", SAT_1530, ("ask", "time_or_verse")),
    ("llamar a Juan 3:30 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("cenar con Mateo 8:15 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("llamar a Daniel 7:30", SAT_1530, ("ask", "time_or_verse")),
    ("llamar a Juan 3:16-18", SAT_1530, ("none",)),  # con rango ya no puede ser una hora
    # Abreviaturas que coinciden con palabras comunes (ajuste 2): se pregunta
    ("leer Sal 23:4 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("leer Is 53:5 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("leer Am 5:24 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("leer Mi 6:8 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("leer Mal 3:10", SAT_1530, ("ask", "time_or_verse")),
    ("leer Os 6:6", SAT_1530, ("ask", "time_or_verse")),
    ("leer Ex 20:3", SAT_1530, ("ask", "time_or_verse")),
    ("leer Rey 3:5", SAT_1530, ("ask", "time_or_verse")),
    # H:MM suelto tras una palabra con mayúscula a mitad de frase: ¿hora o cita?
    ("reunión con Pedro 3:30 mañana", SAT_1530, ("ask", "time_or_verse")),
    ("ver a Lupita 4:45 mañana", SAT_1530, ("ask", "time_or_verse")),
    # ...pero no si es el inicio de la frase, un día, o lleva "a las"
    ("Reunión 3:30 mañana", SAT_1530, ("ok", "2026-10-04 15:30", True)),
    ("ir mañana 3:30", SAT_1530, ("ok", "2026-10-04 15:30", True)),
    ("reunión con Pedro mañana a las 3:30", SAT_1530, ("ok", "2026-10-04 15:30", True)),
]


@pytest.mark.parametrize(("phrase", "now_local", "expected"), BIBLE, ids=[c[0] for c in BIBLE])
def test_citas_biblicas(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)


def test_la_cita_se_queda_en_el_titulo():
    assert run("leer Juan 3:16 mañana").title == "leer Juan 3:16"
    assert run("Juan 15:13 el domingo").title == "Juan 15:13"


def test_la_lista_cerrada_tiene_los_66_libros():
    from asistente.parsing.dates import BIBLE_BOOKS

    assert len(BIBLE_BOOKS) == 66
    assert len(set(BIBLE_BOOKS)) == 66
    assert {"1 Juan", "2 Corintios", "Salmos", "Hechos", "Apocalipsis"} <= set(BIBLE_BOOKS)


def test_nunca_se_descarta_una_cita_en_una_repeticion():
    from asistente.parsing.recurrence import parse_recurrence

    result = parse_recurrence(
        "leer Juan 3:16 todos los días", lambda: local(SAT_1530), TZ, DEFAULT_MORNING
    )
    assert result.status == "ok" and result.has_time is False


# --- Familia 2: marcadores a. m. / p. m. y horas en palabras (reglas 2 y 3) -----------------------
MARKERS_AND_WORDS = [
    ("mañana a las 3 a. m.", SAT_1530, ("ok", "2026-10-04 03:00", True)),
    ("mañana a las 3 a.m.", SAT_1530, ("ok", "2026-10-04 03:00", True)),
    ("mañana a las 3 a m", SAT_1530, ("ok", "2026-10-04 03:00", True)),
    ("mañana a las 3 AM", SAT_1530, ("ok", "2026-10-04 03:00", True)),
    ("mañana a las 3 A. M.", SAT_1530, ("ok", "2026-10-04 03:00", True)),
    ("mañana a las 3 p. m.", SAT_1530, ("ok", "2026-10-04 15:00", True)),
    ("mañana a las 3:30 p.m.", SAT_1530, ("ok", "2026-10-04 15:30", True)),
    ("mañana 8 a. m.", SAT_1530, ("ok", "2026-10-04 08:00", True)),
    ("mañana a la una", SAT_1530, ("ok", "2026-10-04 13:00", True)),
    ("mañana a las dos", SAT_1530, ("ok", "2026-10-04 14:00", True)),
    ("mañana a las cuatro", SAT_1530, ("ok", "2026-10-04 16:00", True)),
    (
        "mañana a las cinco",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-04 05:00", "2026-10-04 17:00"]),
    ),
    ("mañana a las doce", SAT_1530, ("ok", "2026-10-04 12:00", True)),
    ("mañana a las ocho de la noche", SAT_1530, ("ok", "2026-10-04 20:00", True)),
    ("mañana a las diez am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("mañana a mediodía", SAT_1530, ("ok", "2026-10-04 12:00", True)),
    ("mañana al mediodía", SAT_1530, ("ok", "2026-10-04 12:00", True)),
    ("mañana a medio día", SAT_1530, ("ok", "2026-10-04 12:00", True)),
    (
        "mañana a medianoche",
        SAT_1530,
        ("ask", "ambiguous_time", ["2026-10-04 00:00", "2026-10-05 00:00"]),
    ),
    (
        "mañana a las 12 am",
        SAT_1530,
        ("ask", "ambiguous_time", ["2026-10-04 00:00", "2026-10-05 00:00"]),
    ),
    ("mañana a las 3 y 15", SAT_1530, ("ok", "2026-10-04 15:15", True)),
    ("mañana a las 3 y cuarto", SAT_1530, ("ok", "2026-10-04 15:15", True)),
    ("mañana a las 3 y media", SAT_1530, ("ok", "2026-10-04 15:30", True)),
    ("mañana a las dos y cinco", SAT_1530, ("ok", "2026-10-04 14:05", True)),
    ("mañana a la una y media", SAT_1530, ("ok", "2026-10-04 13:30", True)),
    ("mañana a las 12 y media", SAT_1530, ("ok", "2026-10-04 12:30", True)),
    (
        "mañana a las 7 y 20",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-04 07:20", "2026-10-04 19:20"]),
    ),
    (
        "mañana a las siete y media",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-04 07:30", "2026-10-04 19:30"]),
    ),
    ("mañana a las 8 y 15 pm", SAT_1530, ("ok", "2026-10-04 20:15", True)),
    ("mañana a las 4 menos cuarto", SAT_1530, ("ok", "2026-10-04 15:45", True)),
    ("mañana a las 2 menos 5", SAT_1530, ("ok", "2026-10-04 13:55", True)),
    ("mañana a la una menos cuarto", SAT_1530, ("ok", "2026-10-04 12:45", True)),
    (
        "mañana a las 8 menos cuarto",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-04 07:45", "2026-10-04 19:45"]),
    ),
    ("mañana a las 8 menos 10 pm", SAT_1530, ("ok", "2026-10-04 19:50", True)),
    (
        "mañana a las doce menos cuarto",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-04 11:45", "2026-10-04 23:45"]),
    ),
    ("mañana a las 8 y 70", SAT_1530, ("ask", "invalid_time")),
    ("mañana a las 8 menos 70", SAT_1530, ("ask", "invalid_time")),
    # No son hora: "a m" / "a" + palabra, y números sueltos
    ("llevar a mamá mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("mañana comprar 3 a manera", SAT_1530, ("ok", "2026-10-04 09:00", False)),
]


@pytest.mark.parametrize(
    ("phrase", "now_local", "expected"), MARKERS_AND_WORDS, ids=[c[0] for c in MARKERS_AND_WORDS]
)
def test_marcadores_y_horas_en_palabras(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)


# --- Familia 3: "7.30" y números sueltos tras un día (reglas 4 y 6) ------------------------------
LOOSE_NUMBERS = [
    ("mañana 7.30 gimnasio", SAT_1530, ("ask", "dotted_time")),
    ("mañana a las 7.30", SAT_1530, ("ask", "dotted_time")),
    ("a las 7.30", SAT_1530, ("ask", "dotted_time")),
    ("el domingo 19.45 cena", SAT_1530, ("ask", "dotted_time")),
    ("gimnasio 7.30", SAT_1530, ("none",)),  # sin día ni "a las": no parece fecha
    ("comprar 2.50 de pan", SAT_1530, ("none",)),
    ("mañana 7 dentista", SAT_1530, ("ask", "number_after_day")),
    ("mañana 7", SAT_1530, ("ask", "number_after_day")),
    ("el domingo 11 cumpleaños de mamá", SAT_1530, ("ask", "number_after_day")),
    ("hoy 5 llamadas", SAT_1530, ("ask", "number_after_day")),
    ("pasado mañana 3 tareas", SAT_1530, ("ask", "number_after_day")),
    ("el viernes 2 reuniones", SAT_1530, ("ask", "number_after_day")),
    ("en 3 días 2 pastillas", SAT_1530, ("ask", "number_after_day")),
    ("el 12 de octubre 3 tareas", SAT_1530, ("ask", "number_after_day")),
    # Sí son fecha/hora: el número es parte de la hora, de la fecha, o no va pegado al día
    ("mañana 8am", SAT_1530, ("ok", "2026-10-04 08:00", True)),
    ("mañana 7 pm", SAT_1530, ("ok", "2026-10-04 19:00", True)),
    ("mañana 8:30 pm", SAT_1530, ("ok", "2026-10-04 20:30", True)),
    ("mañana 15:30", SAT_1530, ("ok", "2026-10-04 15:30", True)),
    ("tomar 2 pastillas mañana", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("mañana comprar 3 cosas", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("el viernes a las 5 pm 2 cosas", SAT_1530, ("ok", "2026-10-09 17:00", True)),
]


@pytest.mark.parametrize(
    ("phrase", "now_local", "expected"), LOOSE_NUMBERS, ids=[c[0] for c in LOOSE_NUMBERS]
)
def test_numeros_sueltos(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)


def test_repeticion_tambien_pregunta_por_7_30_y_numero_suelto():
    from asistente.parsing.recurrence import parse_recurrence

    def series(text):
        return parse_recurrence(text, lambda: local(SAT_1530), TZ, DEFAULT_MORNING)

    assert series("todos los días 7.30").reason == "dotted_time"
    assert series("cada lunes 7 pastillas").reason == "number_after_day"


# --- Familia 4: "domingo" sin determinante (regla 5) --------------------------------------------
DOMINGO = [
    ("LLAMAR A DOMINGO", SAT_1530, ("ask", "name_or_day")),
    ("llamar a domingo", SAT_1530, ("ask", "name_or_day")),
    ("llamar a Domingo", SAT_1530, ("ask", "name_or_day")),
    ("llamar a Domingo a las 5", SAT_1530, ("ask", "name_or_day")),
    ("llamar a domingo a las 5 pm", SAT_1530, ("ask", "name_or_day")),
    ("LLAMAR A DOMINGO A LAS 5 PM", SAT_1530, ("ask", "name_or_day")),
    ("Domingo me presta el carro a las 3", SAT_1530, ("ask", "name_or_day")),
    ("domingo me toca a las 5 pm", SAT_1530, ("ask", "name_or_day")),  # (c) inicio + "me"
    ("Domingo te llama a las 5 pm", SAT_1530, ("ask", "name_or_day")),
    ("regalo para Domingo", SAT_1530, ("ask", "name_or_day")),  # (b) mayúscula a mitad de frase
    ("reunión DOMINGO a las 5 pm", SAT_1530, ("ask", "name_or_day")),
    ("cenar con domingo a las 5 pm", SAT_1530, ("ask", "name_or_day")),  # (a) "con"
    # Cualquier otro caso es fecha (regla 5 revisada)
    ("ensayo domingo 5pm", SAT_1530, ("ok", "2026-10-04 17:00", True)),
    ("domingo 20:00", SAT_1530, ("ok", "2026-10-04 20:00", True)),
    ("Domingo ensayo 5pm", SAT_1530, ("ok", "2026-10-04 17:00", True)),
    ("domingo misa 10 am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("regalo para domingo", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("Domingo a las 5 pm", SAT_1530, ("ok", "2026-10-04 17:00", True)),
    ("REUNIÓN DOMINGO A LAS 5 PM", SAT_1530, ("ok", "2026-10-04 17:00", True)),  # todo mayúsculas
    ("MISA DOMINGO 10 AM", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    # Con determinante es fecha, con cualquier capitalización
    ("misa el domingo a las 10 am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("MISA EL DOMINGO A LAS 10 AM", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("misa este Domingo a las 10 am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("misa para el domingo a las 10 am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("misa domingo que viene a las 10 am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    ("misa el próximo DOMINGO a las 10 am", SAT_1530, ("ok", "2026-10-04 10:00", True)),
    # Los otros días no son nombres propios
    ("misa lunes a las 10 am", SAT_1530, ("ok", "2026-10-05 10:00", True)),
    ("LLAMAR A MARTES A LAS 5 PM", SAT_1530, ("ok", "2026-10-06 17:00", True)),
    # Con otro día claro, "Domingo" es el nombre y manda el otro día
    ("llamar a Domingo mañana a las 5 pm", SAT_1530, ("ok", "2026-10-04 17:00", True)),
    ("LLAMAR A DOMINGO MAÑANA A LAS 5 PM", SAT_1530, ("ok", "2026-10-04 17:00", True)),
]


@pytest.mark.parametrize(("phrase", "now_local", "expected"), DOMINGO, ids=[c[0] for c in DOMINGO])
def test_domingo(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)


@pytest.mark.parametrize(
    ("phrase", "title"),
    [
        ("llamar a Domingo mañana a las 5 pm", "llamar a Domingo"),
        ("LLAMAR A DOMINGO MAÑANA A LAS 5 PM", "LLAMAR A DOMINGO"),
        ("llamar a Domingo a las 5", "llamar a Domingo"),
        ("LLAMAR A DOMINGO", "LLAMAR A DOMINGO"),
    ],
)
def test_el_titulo_conserva_domingo(phrase, title):
    assert run(phrase).title == title


# --- Familia 5: fechas con aspecto de fecha (regla 7) y 29 de febrero (regla 11) -----------------
FEB29 = "2028-02-29 16:00"
DATES = [
    # No soportadas: se pregunta, nunca se descartan en silencio
    ("el 20 de este mes", SAT_1530, ("ask", "unsupported_date")),
    ("pagar el 20 de este mes", SAT_1530, ("ask", "unsupported_date")),
    ("1ro de noviembre", SAT_1530, ("ask", "unsupported_date")),
    ("1º de noviembre", SAT_1530, ("ask", "unsupported_date")),
    ("1er de noviembre", SAT_1530, ("ask", "unsupported_date")),
    ("primero de noviembre", SAT_1530, ("ask", "unsupported_date")),
    ("en 3 meses", SAT_1530, ("ask", "unsupported_date")),
    ("dentro de 2 meses", SAT_1530, ("ask", "unsupported_date")),
    ("en un año", SAT_1530, ("ask", "unsupported_date")),
    ("el próximo mes", SAT_1530, ("ask", "unsupported_date")),
    ("fin de mes", SAT_1530, ("ask", "unsupported_date")),
    ("la semana que viene", SAT_1530, ("ask", "unsupported_date")),
    ("esta semana", SAT_1530, ("ask", "unsupported_date")),
    ("el 5 del mes que viene", SAT_1530, ("ask", "unsupported_date")),
    ("comprar el 3 de espadas", SAT_1530, ("ask", "unsupported_date")),
    ("el 5 dentista", SAT_1530, ("ask", "unsupported_date")),
    # Soportadas: "el N" (siguiente ocurrencia, hoy cuenta)
    ("pagar renta el 5", SAT_1530, ("ok", "2026-10-05 09:00", False)),
    ("el 5 a las 3 pm", SAT_1530, ("ok", "2026-10-05 15:00", True)),
    ("el 5, pagar renta", SAT_1530, ("ok", "2026-10-05 09:00", False)),
    ("el 20 a las 8 pm", SAT_1530, ("ok", "2026-10-20 20:00", True)),
    ("el 3 a las 8 pm", SAT_1530, ("ok", "2026-10-03 20:00", True)),
    ("el 3", SAT_1530, ("ask", "past", ["2026-11-03 09:00"])),  # hoy 09:00 ya pasó
    ("el 3", "2026-10-03 08:00", ("ok", "2026-10-03 09:00", False)),
    ("el 31", SAT_1530, ("ok", "2026-10-31 09:00", False)),
    ("el 31", "2026-04-15 10:00", ("ok", "2026-05-31 09:00", False)),  # abril no tiene 31
    ("el 5", "2026-12-20 10:00", ("ok", "2027-01-05 09:00", False)),
    ("el 40", SAT_1530, ("ask", "invalid_date")),
    ("el 0", SAT_1530, ("ask", "invalid_date")),
    # Soportadas: "N de mes" y "en N días/semanas"
    ("el 12 de octubre", SAT_1530, ("ok", "2026-10-12 09:00", False)),
    ("12 de octubre a las 5 pm", SAT_1530, ("ok", "2026-10-12 17:00", True)),
    ("el 3 de octubre", SAT_1530, ("ask", "past", ["2027-10-03 09:00"])),
    ("el 2 de octubre de 2027", SAT_1530, ("ok", "2027-10-02 09:00", False)),
    ("en 3 días", SAT_1530, ("ok", "2026-10-06 09:00", False)),
    ("en 1 día", SAT_1530, ("ok", "2026-10-04 09:00", False)),
    ("en 2 semanas", SAT_1530, ("ok", "2026-10-17 09:00", False)),
    ("dentro de una semana", SAT_1530, ("ok", "2026-10-10 09:00", False)),
    ("en tres días a las 5 pm", SAT_1530, ("ok", "2026-10-06 17:00", True)),
    # 29 de febrero: la siguiente fecha bisiesta REAL
    ("el 29 de febrero", FEB29, ("ask", "past", ["2032-02-29 09:00"])),
    ("el 29 de febrero", "2028-02-29 08:00", ("ok", "2028-02-29 09:00", False)),
    ("el 29 de febrero a las 5 pm", FEB29, ("ok", "2028-02-29 17:00", True)),
    (
        "el 29 de febrero",
        "2096-03-01 10:00",
        ("ok", "2104-02-29 09:00", False),
    ),  # 2100 no es bisiesto
    ("el 29 de febrero", "2100-01-01 10:00", ("ok", "2104-02-29 09:00", False)),
    ("el 29 de febrero", SAT_1530, ("ok", "2028-02-29 09:00", False)),
    ("el 29 de febrero de 2027", SAT_1530, ("ask", "invalid_date")),
]


@pytest.mark.parametrize(
    ("phrase", "now_local", "expected"),
    DATES,
    ids=[f"{c[0]} @ {c[1]}" for c in DATES],
)
def test_fechas_con_aspecto_de_fecha(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)


# --- Familia 6: repeticiones (regla 8) y flujo "primero la repetición, luego la fecha" ---------
# (frase, reloj, esperado): ("series", rrule, primera local, ¿trae hora?) | ("once", local)
#                           | ("ask", razón) | ("none",)
SERIES = [
    (
        "todos los lunes a las 7 pm",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=MO", "2026-10-05 19:00", True),
    ),
    (
        "todos los lunes 7 pm",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=MO", "2026-10-05 19:00", True),
    ),
    (
        "todos los sábados a las 6 pm",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=SA", "2026-10-03 18:00", True),
    ),
    (
        "todos los domingos 10 am misa",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=SU", "2026-10-04 10:00", True),
    ),
    ("todos los martes", SAT_1530, ("series", "FREQ=WEEKLY;BYDAY=TU", "2026-10-06 09:00", False)),
    ("cada día a las 8 pm", SAT_1530, ("series", "FREQ=DAILY", "2026-10-03 20:00", True)),
    ("cada dia", SAT_1530, ("series", "FREQ=DAILY", "2026-10-04 09:00", False)),
    ("diario a las 8 pm", SAT_1530, ("series", "FREQ=DAILY", "2026-10-03 20:00", True)),
    ("diaria 8 pm tomar pastilla", SAT_1530, ("series", "FREQ=DAILY", "2026-10-03 20:00", True)),
    ("diario", SAT_1530, ("series", "FREQ=DAILY", "2026-10-04 09:00", False)),
    ("todos los días a las 8 pm", SAT_1530, ("series", "FREQ=DAILY", "2026-10-03 20:00", True)),
    (
        "cada viernes a las 5 pm",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=FR", "2026-10-09 17:00", True),
    ),
    (
        "de lunes a viernes a las 7 am",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "2026-10-05 07:00", True),
    ),
    (
        "leer Juan 3:16 todos los lunes",
        SAT_1530,
        ("series", "FREQ=WEEKLY;BYDAY=MO", "2026-10-05 09:00", False),
    ),
    # Un solo aviso, sin repetición
    ("mañana a las 8 pm", SAT_1530, ("once", "2026-10-04 20:00")),
    ("el lunes a las 7 pm", SAT_1530, ("once", "2026-10-05 19:00")),
    ("comprar leche", SAT_1530, ("none",)),
    # Palabra de repetición que no se entiende como serie: SIEMPRE se pregunta, nunca un aviso único
    ("cada mes", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("cada semana", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("semanal", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("mensual a las 8 pm", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("pagar renta mensual", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("pagar renta el 5 mensual", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("diariamente a las 8 pm", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("todas las noches a las 9 pm", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("cada 2 semanas", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("cada mañana", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("tomar pastilla cada 8 horas", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("todos los santos", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("cada quincena", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("mañana a las 8 pm cada semana", SAT_1530, ("ask", "unrecognized_recurrence")),
    ("todos los lunes cada 2 semanas", SAT_1530, ("ask", "unrecognized_recurrence")),
    # Serie reconocida pero con algo más: se pregunta por eso
    ("todos los lunes a las 7 y 20", SAT_1530, ("ask", "ambiguous_meridiem")),
    ("cada lunes y jueves", SAT_1530, ("ask", "two_dates")),
    ("todos los días mañana", SAT_1530, ("ask", "two_dates")),
]


def schedule(phrase: str, now_local: str = SAT_1530):
    from asistente.parsing.recurrence import parse_schedule

    return parse_schedule(phrase, lambda: local(now_local), TZ, DEFAULT_MORNING)


@pytest.mark.parametrize(("phrase", "now_local", "expected"), SERIES, ids=[c[0] for c in SERIES])
def test_repeticiones(phrase, now_local, expected):
    result = schedule(phrase, now_local)
    kind = expected[0]
    assert result.kind == kind, (phrase, result)
    if kind == "series":
        assert result.series.rrule == expected[1], (phrase, result)
        shown = to_local(result.series.first_at_utc, TZ).strftime("%Y-%m-%d %H:%M")
        assert shown == expected[2], (phrase, result)
        assert result.series.has_time is expected[3], (phrase, result)
    elif kind == "once":
        shown = to_local(result.when.when_utc, TZ).strftime("%Y-%m-%d %H:%M")
        assert shown == expected[1], (phrase, result)
    elif kind == "ask":
        assert result.reason == expected[1], (phrase, result)


def test_parse_when_solo_tampoco_guarda_un_aviso_unico_con_palabras_de_repeticion():
    # Defensa en profundidad: aunque alguien llame solo a parse_when, no devuelve "ok"
    for phrase in ("cada mes a las 8 pm", "mañana a las 8 pm semanal", "todos los santos mañana"):
        result = run(phrase)
        assert (result.status, result.reason) == ("ask", "unrecognized_recurrence"), phrase


def test_el_flujo_prueba_primero_la_repeticion_y_luego_la_fecha(monkeypatch):
    from asistente.parsing import recurrence

    calls: list[str] = []
    real_recurrence, real_when = recurrence.parse_recurrence, recurrence.parse_when

    def spy_recurrence(*args, **kwargs):
        calls.append("recurrence")
        return real_recurrence(*args, **kwargs)

    def spy_when(*args, **kwargs):
        calls.append("when")
        return real_when(*args, **kwargs)

    monkeypatch.setattr(recurrence, "parse_recurrence", spy_recurrence)
    # La fecha suelta solo se consulta cuando la repetición dijo "none"
    calls.clear()
    monkeypatch.setattr(recurrence, "_parse_single", spy_when)
    assert schedule("mañana a las 8 pm").kind == "once"
    assert calls == ["recurrence", "when"]
    calls.clear()
    assert schedule("todos los lunes a las 7 pm").kind == "series"
    assert calls == ["recurrence"]
    calls.clear()
    assert schedule("cada mes").kind == "ask"
    assert calls == ["recurrence"]


def test_la_constante_de_palabras_de_repeticion_es_compartida():
    from asistente.parsing import dates, recurrence

    assert recurrence.has_recurrence_keyword is dates.has_recurrence_keyword


# --- Familia 6b: "diario" como sustantivo no es una serie ---------------------------------------
DIARIO = [
    # No es repetición: "diario" es un sustantivo (mi diario, el diario, un diario...)
    ("escribir en mi diario mañana", SAT_1530, ("once", "2026-10-04 09:00")),
    ("escribir en mis diarios mañana", SAT_1530, ("once", "2026-10-04 09:00")),
    ("leer el diario mañana", SAT_1530, ("once", "2026-10-04 09:00")),
    ("comprar un diario mañana a las 8 am", SAT_1530, ("once", "2026-10-04 08:00")),
    ("recoger el diario del lunes", SAT_1530, ("once", "2026-10-05 09:00")),
    ("llevar su diario mañana", SAT_1530, ("once", "2026-10-04 09:00")),
    ("traer tu diario mañana", SAT_1530, ("once", "2026-10-04 09:00")),
    ("escribir en mi diario", SAT_1530, ("none",)),
    # Sí es repetición
    ("ejercicio diario", SAT_1530, ("series", "FREQ=DAILY", "2026-10-04 09:00", False)),
    ("diario a las 8", SAT_1530, ("ask", "ambiguous_meridiem")),
    ("diario a las 8 pm", SAT_1530, ("series", "FREQ=DAILY", "2026-10-03 20:00", True)),
    ("ejercicio diario a las 7 pm", SAT_1530, ("series", "FREQ=DAILY", "2026-10-03 19:00", True)),
    (
        "escribir mi diario todos los días a las 9 pm",
        SAT_1530,
        ("series", "FREQ=DAILY", "2026-10-03 21:00", True),
    ),
    ("pagar mensual el diario", SAT_1530, ("ask", "unrecognized_recurrence")),
]


@pytest.mark.parametrize(("phrase", "now_local", "expected"), DIARIO, ids=[c[0] for c in DIARIO])
def test_diario_sustantivo_o_repeticion(phrase, now_local, expected):
    result = schedule(phrase, now_local)
    assert result.kind == expected[0], (phrase, result)
    if expected[0] == "series":
        assert result.series.rrule == expected[1]
        assert to_local(result.series.first_at_utc, TZ).strftime("%Y-%m-%d %H:%M") == expected[2]
        assert result.series.has_time is expected[3]
    elif expected[0] == "once":
        assert to_local(result.when.when_utc, TZ).strftime("%Y-%m-%d %H:%M") == expected[1]
    elif expected[0] == "ask":
        assert result.reason == expected[1]


def test_parse_when_solo_tampoco_trata_mi_diario_como_serie():
    check(run("escribir en mi diario mañana"), ("ok", "2026-10-04 09:00", False))


# --- Familia 7: candidatos am/pm sin día (regla 9) y "mañana" de madrugada (regla 10) ------------
SUN_0040 = "2026-10-04 00:40"
SAT_2300 = "2026-10-03 23:00"
MERIDIEM = [
    # Sin día: la próxima ocurrencia futura de CADA lectura; si la am llega antes, ambas
    ("a las 4", SAT_2300, ("ask", "ambiguous_meridiem", ["2026-10-04 04:00", "2026-10-04 16:00"])),
    ("a las 3", SAT_1530, ("ask", "ambiguous_meridiem", ["2026-10-04 03:00", "2026-10-04 15:00"])),
    (
        "a las 2 y media",
        SAT_2300,
        ("ask", "ambiguous_meridiem", ["2026-10-04 02:30", "2026-10-04 14:30"]),
    ),
    (
        "a las 4",
        "2026-10-03 02:00",
        ("ask", "ambiguous_meridiem", ["2026-10-03 04:00", "2026-10-03 16:00"]),
    ),
    ("a las 8", SAT_1530, ("ask", "ambiguous_meridiem", ["2026-10-03 20:00", "2026-10-04 08:00"])),
    ("a las 8", SAT_2300, ("ask", "ambiguous_meridiem", ["2026-10-04 08:00", "2026-10-04 20:00"])),
    (
        "a las 8",
        "2026-10-03 02:00",
        ("ask", "ambiguous_meridiem", ["2026-10-03 08:00", "2026-10-03 20:00"]),
    ),
    (
        "a las siete y media",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-03 19:30", "2026-10-04 07:30"]),
    ),
    # Si la pm llega primero y la hora es de 1 a 4, queda la de la tarde (marcada como asumida)
    ("a las 4", SAT_1530, ("ok", "2026-10-03 16:00", True)),
    ("a las 2", "2026-10-03 10:00", ("ok", "2026-10-03 14:00", True)),
    # Con día explícito: un candidato único sigue siendo ASK con ese candidato (nunca ok)
    ("hoy a las 8", SAT_1530, ("ask", "ambiguous_meridiem", ["2026-10-03 20:00"])),
    ("hoy a las 6", SAT_1530, ("ask", "ambiguous_meridiem", ["2026-10-03 18:00"])),
    (
        "hoy a las 8",
        "2026-10-03 05:00",
        ("ask", "ambiguous_meridiem", ["2026-10-03 08:00", "2026-10-03 20:00"]),
    ),
    (
        "mañana a las 8",
        SAT_1530,
        ("ask", "ambiguous_meridiem", ["2026-10-04 08:00", "2026-10-04 20:00"]),
    ),
    # Con marcador, 24 h o mediodía no se pregunta
    ("a las 8 pm", SAT_1530, ("ok", "2026-10-03 20:00", True)),
    ("a las 16:00", SAT_2300, ("ask", "past", ["2026-10-04 16:00"])),  # ya pasó: se pregunta
    ("a las 12", SAT_2300, ("ask", "past", ["2026-10-04 12:00"])),
]


@pytest.mark.parametrize(
    ("phrase", "now_local", "expected"), MERIDIEM, ids=[f"{c[0]} @ {c[1]}" for c in MERIDIEM]
)
def test_candidatos_am_pm(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)


def test_la_hora_asumida_sigue_marcada_como_asumida():
    assert run("a las 4").meridiem_inferred is True


TODAY_OR_TOMORROW = [
    # Entre las 00:00 y las 05:00 locales, "mañana" pregunta "¿hoy o mañana?"
    (
        "mañana a las 8 am",
        SUN_0040,
        ("ask", "today_or_tomorrow", ["2026-10-04 08:00", "2026-10-05 08:00"]),
    ),
    ("mañana", SUN_0040, ("ask", "today_or_tomorrow", ["2026-10-04 09:00", "2026-10-05 09:00"])),
    (
        "mañana a las 8 de la mañana",
        SUN_0040,
        ("ask", "today_or_tomorrow", ["2026-10-04 08:00", "2026-10-05 08:00"]),
    ),
    (
        "mañana a las 8 pm",
        "2026-10-04 04:59",
        ("ask", "today_or_tomorrow", ["2026-10-04 20:00", "2026-10-05 20:00"]),
    ),
    (
        "mañana 3 pm",
        "2026-10-04 00:00",
        ("ask", "today_or_tomorrow", ["2026-10-04 15:00", "2026-10-05 15:00"]),
    ),
    ("mañana a las 8", SUN_0040, ("ask", "today_or_tomorrow")),  # primero el día; la hora después
    (
        "mañana por la mañana",
        SUN_0040,
        ("ask", "unrecognized_time"),
    ),  # el parser no la reconoce como hora
    # Fuera de la ventana, o si la lectura de hoy ya pasó, no hay duda
    ("mañana a las 8 am", "2026-10-04 05:00", ("ok", "2026-10-05 08:00", True)),
    ("mañana a las 8 am", SAT_1530, ("ok", "2026-10-04 08:00", True)),
    ("mañana a las 3 am", "2026-10-04 04:30", ("ok", "2026-10-05 03:00", True)),
    # "pasado mañana" no aplica
    ("pasado mañana a las 8 am", SUN_0040, ("ok", "2026-10-06 08:00", True)),
    ("pasado mañana", SUN_0040, ("ok", "2026-10-06 09:00", False)),
    # Otros días tampoco
    ("hoy a las 8 am", SUN_0040, ("ok", "2026-10-04 08:00", True)),
    ("el lunes a las 8 am", SUN_0040, ("ok", "2026-10-05 08:00", True)),
]


@pytest.mark.parametrize(
    ("phrase", "now_local", "expected"),
    TODAY_OR_TOMORROW,
    ids=[f"{c[0]} @ {c[1]}" for c in TODAY_OR_TOMORROW],
)
def test_manana_de_madrugada_pregunta_hoy_o_manana(phrase, now_local, expected):
    check(run(phrase, now_local), expected, phrase)
