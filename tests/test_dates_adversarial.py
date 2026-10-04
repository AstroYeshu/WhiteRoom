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
