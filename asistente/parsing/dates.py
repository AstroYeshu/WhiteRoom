"""Fechas y horas en español con una gramática CERRADA (sin librerías de fechas).

Idea: reconocer solo un conjunto pequeño de expresiones y entenderlas bien. Si algo no
encaja entero (dos fechas, hora dudosa, fecha pasada...) NO se adivina: se devuelve
`status="ask"` con la razón y el handler pregunta con botones. Un recordatorio nunca se
crea con una hora dudosa ni en el pasado.

Todo el texto se "pliega" (minúsculas y sin acentos, carácter por carácter) para buscar con
expresiones regulares; como el largo no cambia, las posiciones sirven para quitar del texto
original los trozos reconocidos y dejar el título limpio.

Las reglas están documentadas en `docs/PLAN_FASE1.md` (sección del parser de fechas).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from asistente.timeutil import Clock, local_to_utc, to_local

WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")  # = weekday()
WEEKDAY_NAMES_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTH_NAMES_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_MONTHS = {name.replace("é", "e"): i + 1 for i, name in enumerate(MONTH_NAMES_ES)}
_MONTHS["setiembre"] = 9
_NUMBER_WORDS = {
    "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}  # fmt: skip
_MAX_YEARS_AHEAD = 8  # cubre el 29 de febrero (el peor hueco entre años bisiestos es 8 años)
_GLUE_WORDS = {"para", "a", "de", "en", "y", "por", "al", "que"}
_REMINDER_VERBS = {"recordar", "recordarme", "recuerdame"}  # "recuérdame", sin acentos
# Horas sin am/pm que se PREGUNTAN (ambos extremos incluidos). Por debajo del rango se asume
# tarde (1-4) y por encima mañana. Vive en `settings` (meridiem_ask_range).
DEFAULT_MERIDIEM_ASK_RANGE = (5, 11)
_SMALL_HOURS_END = 5  # antes de las 05:00 locales "mañana" puede significar hoy (regla 10)

Status = Literal["none", "ok", "ask"]


@dataclass(frozen=True)
class WhenResult:
    """Resultado de interpretar la fecha de un texto.

    - `none`: no hay fecha en el texto.
    - `ok`: fecha resuelta (`when_utc`); `has_time=False` si se usó la hora por defecto.
    - `ask`: hay que preguntar; `reason` dice por qué y `candidates` son opciones futuras
      ya resueltas (con `ambiguous_meridiem`: la misma hora en am y en pm).

    `meridiem_inferred` es True si la hora venía sin am/pm y se asumió (1-4 → tarde), para que
    el handler muestre el botón "Cambiar a am/pm".
    """

    status: Status
    title: str
    when_utc: datetime | None = None
    has_time: bool = False
    reason: str | None = None
    candidates: tuple[datetime, ...] = ()
    meridiem_inferred: bool = False


@dataclass
class Hit:
    """Un trozo reconocido: posición en el texto, tipo y valor."""

    start: int
    end: int
    kind: str
    value: object
    inferred: bool = False  # am/pm asumido por la regla
    raw: tuple[int, int] | None = None  # (hora, minuto) tal como se escribió, para las horas


def fold(text: str) -> str:
    """Minúsculas y sin acentos, conservando el largo (1 carácter -> 1 carácter)."""
    return "".join(unicodedata.normalize("NFD", ch)[0].lower()[:1] for ch in text)


# --- Citas bíblicas ------------------------------------------------------------------------
# "Juan 3:16" no es una hora. Lista CERRADA: los 66 libros en español (con las variantes
# numeradas) más las abreviaturas habituales. Las abreviaturas que coinciden con palabras
# comunes (Mi, Mal, Os, Is, Am, Ex, Sal, Rey) no se deciden: se pregunta (`time_or_verse`).

_NONE = frozenset({""})  # sin número delante
_N12 = frozenset({"1", "2"})
_OPT123 = frozenset({"", "1", "2", "3"})  # "Juan", "1 Juan", "2 Juan", "3 Juan"
_BOOKS_BASE: dict[str, tuple[frozenset[str], str]] = {  # nombre plegado -> (números, nombre)
    "genesis": (_NONE, "Génesis"), "exodo": (_NONE, "Éxodo"), "levitico": (_NONE, "Levítico"),
    "numeros": (_NONE, "Números"), "deuteronomio": (_NONE, "Deuteronomio"),
    "josue": (_NONE, "Josué"), "jueces": (_NONE, "Jueces"), "rut": (_NONE, "Rut"),
    "samuel": (_N12, "Samuel"), "reyes": (_N12, "Reyes"), "cronicas": (_N12, "Crónicas"),
    "esdras": (_NONE, "Esdras"), "nehemias": (_NONE, "Nehemías"), "ester": (_NONE, "Ester"),
    "job": (_NONE, "Job"), "salmos": (_NONE, "Salmos"), "salmo": (_NONE, "Salmos"),
    "proverbios": (_NONE, "Proverbios"), "eclesiastes": (_NONE, "Eclesiastés"),
    "cantares": (_NONE, "Cantares"), "cantar de los cantares": (_NONE, "Cantares"),
    "isaias": (_NONE, "Isaías"), "jeremias": (_NONE, "Jeremías"),
    "lamentaciones": (_NONE, "Lamentaciones"), "ezequiel": (_NONE, "Ezequiel"),
    "daniel": (_NONE, "Daniel"), "oseas": (_NONE, "Oseas"), "joel": (_NONE, "Joel"),
    "amos": (_NONE, "Amós"), "abdias": (_NONE, "Abdías"), "jonas": (_NONE, "Jonás"),
    "miqueas": (_NONE, "Miqueas"), "nahum": (_NONE, "Nahúm"), "habacuc": (_NONE, "Habacuc"),
    "sofonias": (_NONE, "Sofonías"), "hageo": (_NONE, "Hageo"), "zacarias": (_NONE, "Zacarías"),
    "malaquias": (_NONE, "Malaquías"), "mateo": (_NONE, "Mateo"), "marcos": (_NONE, "Marcos"),
    "lucas": (_NONE, "Lucas"), "juan": (_OPT123, "Juan"), "hechos": (_NONE, "Hechos"),
    "romanos": (_NONE, "Romanos"), "corintios": (_N12, "Corintios"),
    "galatas": (_NONE, "Gálatas"), "efesios": (_NONE, "Efesios"),
    "filipenses": (_NONE, "Filipenses"), "colosenses": (_NONE, "Colosenses"),
    "tesalonicenses": (_N12, "Tesalonicenses"), "timoteo": (_N12, "Timoteo"),
    "tito": (_NONE, "Tito"), "filemon": (_NONE, "Filemón"), "hebreos": (_NONE, "Hebreos"),
    "santiago": (_NONE, "Santiago"), "pedro": (_N12, "Pedro"), "judas": (_NONE, "Judas"),
    "apocalipsis": (_NONE, "Apocalipsis"),
}  # fmt: skip
_ABBREVIATIONS: dict[str, tuple[frozenset[str], str]] = {  # abreviatura plegada -> (números, libro)
    "gn": (_NONE, "Génesis"), "gen": (_NONE, "Génesis"), "lv": (_NONE, "Levítico"),
    "nm": (_NONE, "Números"), "dt": (_NONE, "Deuteronomio"), "jos": (_NONE, "Josué"),
    "rt": (_NONE, "Rut"), "sam": (_N12, "Samuel"), "cr": (_N12, "Crónicas"),
    "pr": (_NONE, "Proverbios"), "prov": (_NONE, "Proverbios"), "jer": (_NONE, "Jeremías"),
    "dn": (_NONE, "Daniel"), "ez": (_NONE, "Ezequiel"), "mt": (_NONE, "Mateo"),
    "mc": (_NONE, "Marcos"), "lc": (_NONE, "Lucas"), "jn": (_OPT123, "Juan"),
    "hch": (_NONE, "Hechos"), "ro": (_NONE, "Romanos"), "co": (_N12, "Corintios"),
    "cor": (_N12, "Corintios"), "ga": (_NONE, "Gálatas"), "ef": (_NONE, "Efesios"),
    "fil": (_NONE, "Filipenses"), "col": (_NONE, "Colosenses"), "ts": (_N12, "Tesalonicenses"),
    "ti": (_N12, "Timoteo"), "tim": (_N12, "Timoteo"), "heb": (_NONE, "Hebreos"),
    "stg": (_NONE, "Santiago"), "pe": (_N12, "Pedro"), "jud": (_NONE, "Judas"),
    "ap": (_NONE, "Apocalipsis"),
}  # fmt: skip
# Abreviaturas que son también palabras comunes: ante la duda, se pregunta.
_AMBIGUOUS_ABBREVIATIONS = frozenset({"mi", "mal", "os", "is", "am", "ex", "sal", "rey"})
# Nombres de persona que son también libros: "llamar a Juan 3:30" es una hora, "leer Juan 3:16" no.
_PERSON_BOOKS = frozenset(
    {"juan", "mateo", "marcos", "lucas", "santiago", "daniel", "samuel", "tito", "timoteo", "josue"}
)
_BOOK_NUMBERS: dict[str, frozenset[str]] = {
    **{key: numbers for key, (numbers, _) in _BOOKS_BASE.items()},
    **{key: numbers for key, (numbers, _) in _ABBREVIATIONS.items()},
    **dict.fromkeys(_AMBIGUOUS_ABBREVIATIONS, _NONE),
}


def _canonical_books() -> tuple[str, ...]:
    """Los 66 libros: la forma numerada cuenta aparte ("1 Juan"); "Juan" una sola vez."""
    names: list[str] = []
    for key, (numbers, name) in _BOOKS_BASE.items():
        if key in ("salmo", "cantar de los cantares"):
            continue  # variantes del mismo libro
        names.extend(f"{n} {name}" if n else name for n in sorted(numbers))
    return tuple(names)


BIBLE_BOOKS = _canonical_books()
_BOOK_ALT = "|".join(sorted(map(re.escape, _BOOK_NUMBERS), key=len, reverse=True))
_RE_CITATION = re.compile(
    r"(?<![\w])(?:(?P<n>[123])\s*)?(?P<b>" + _BOOK_ALT + r")\.?\s*"
    r"(?P<c>\d{1,3}):(?P<v>\d{1,3})(?P<rng>\s*[-–]\s*\d{1,3})?(?![\d:])"
)
_RE_PRECEDED_BY_A_CON = re.compile(r"\b(?:a|con)\s+$")
_RE_PREV_WORD = re.compile(r"(\w+)\s*$")
_DAY_WORDS = frozenset({"manana", "hoy", "pasado", *WEEKDAYS})


def _person_then_time(folded: str, match: re.Match[str]) -> bool:
    """¿"a/con <nombre> H:MM" ("llamar a Juan 3:30")? Entonces es dudoso: hora o cita."""
    verse = match["v"]
    return (
        not match["n"]
        and match["b"] in _PERSON_BOOKS
        and not match["rng"]
        and len(verse) == 2
        and int(match["c"]) <= 23
        and int(verse) <= 59
        and bool(_RE_PRECEDED_BY_A_CON.search(folded[: match.start()]))
    )


def mask_citations(folded: str) -> tuple[str, bool]:
    """Enmascara las citas bíblicas ("Juan 3:16") para que no cuenten como hora.

    Devuelve (texto plegado con las citas en blanco, ¿hay duda hora/cita?). Hay duda con una
    abreviatura que es también palabra común (Sal, Is, Am...) y con un nombre de persona
    precedido de "a"/"con" y seguido de una hora válida ("llamar a Juan 3:30"): ahí se pregunta.
    """
    doubt = False
    for match in list(_RE_CITATION.finditer(folded)):
        book, number = match["b"], match["n"] or ""
        if book in _AMBIGUOUS_ABBREVIATIONS or _person_then_time(folded, match):
            doubt = True
        elif number not in _BOOK_NUMBERS[book]:
            continue  # "Samuel 3:16" sin número, "2 Rut 3:16": no es una cita de la lista
        folded = _mask(folded, match.start(), match.end())
    return folded, doubt


def split_doubtful_weak(original: str, weak: list[Hit]) -> tuple[list[Hit], bool]:
    """Separa las horas sueltas `H:MM` que siguen a una palabra con mayúscula a mitad de frase.

    "reunión con Pedro 3:30 mañana": ¿hora o cita? No se decide: devuelve (las que sí valen,
    ¿hubo alguna dudosa?). Esas horas dudosas no se usan como hora.
    """
    kept: list[Hit] = []
    doubtful = False
    has_lowercase = any(ch.islower() for ch in original)
    for hit in weak:
        before = original[: hit.start]
        word = _RE_PREV_WORD.search(before)
        if (
            word
            and has_lowercase
            and word[1][0].isupper()
            and before[: word.start()].strip()
            and fold(word[1]) not in _DAY_WORDS | _GLUE_WORDS
        ):
            doubtful = True
        else:
            kept.append(hit)
    return kept, doubtful


# --- Horas ---------------------------------------------------------------------------------

_HOUR_WORDS = {
    "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
}  # fmt: skip
_MINUTE_WORDS = {"cinco": 5, "diez": 10, "veinte": 20, "veinticinco": 25, "cuarto": 15, "media": 30}
_MINUTE_ALT = r"\d{1,2}|" + "|".join(_MINUTE_WORDS)
# Una sola expresión para toda hora: "a las 8", "a la una", "3:30", "8 pm", "8 a. m.",
# con "y cuarto / y media / y 15 / y cinco" o "menos cuarto / menos 10". Las palabras ("dos", "una")
# solo valen tras "a la(s)"; un número sin "a las", sin ":" y sin marcador NO es hora.
_RE_CLOCK = re.compile(
    r"(?:\ba\s+las?\s+(?P<hw>\d{1,2}|"
    + "|".join(_HOUR_WORDS)
    + r")\b(?!\.\d)|(?<![\w:.])(?P<hd>\d{1,2}))"
    r"(?::(?P<m>[0-5]\d)(?![\d:]))?"
    r"(?:\s+(?:y\s+(?P<plus>" + _MINUTE_ALT + r")|menos\s+(?P<minus>" + _MINUTE_ALT + r"))\b)?"
    r"(?:\s*(?P<ap>[ap])\s*\.?\s*m\b\.?|\s+(?:de|por|en)\s+la\s+(?P<per>manana|tarde|noche|madrugada)\b)?"
)
_RE_NOON = re.compile(r"\b(?:a\s+|al\s+)?(?:mediodia|medio\s+dia)\b")
_RE_MIDNIGHT = re.compile(r"\b(?:a\s+|a\s+la\s+)?medianoche\b")
# Restos que parecen una hora pero no se entendieron: ante la duda se pregunta.
RE_TIME_LEFTOVER = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*[ap]\s*\.?\s*m\b|\ba\s+las?\s+(?:\d|"
    + "|".join(_HOUR_WORDS)
    + r")\b"
    r"|\b(?:de|por|en)\s+la\s+(?:manana|tarde|noche|madrugada)\b"
    r"|\besta\s+(?:manana|tarde|noche)\b|\by\s+(?:media|cuarto)\b|\bmenos\s+(?:cuarto|\d)"
)
# Palabras que anuncian una REPETICIÓN. La usan `dates.py` y `recurrence.py`: si aparece una y no
# se entendió como serie, se pregunta; jamás se guarda un aviso único.
RECURRENCE_KEYWORD_ALT = (
    r"todos\s+los|todas\s+las|cada|diari(?:o|a|os|as|amente)"
    r"|(?:semanal|mensual|quincenal|anual)(?:es|mente)?"
)
RE_RECURRENCE_KEYWORD = re.compile(r"\b(?:" + RECURRENCE_KEYWORD_ALT + r")\b")
# "diario" como sustantivo ("escribir en mi diario", "el diario", "un diario"): no es una serie.
_RE_NOUN_DETERMINER_BEFORE = re.compile(r"\b(?:mi|mis|el|un|del|su|tu)\s+$")


def is_noun_diario(folded: str, start: int) -> bool:
    """¿La palabra que empieza en `start` es "diario" precedido de mi/mis/el/un/del/su/tu?"""
    return folded.startswith("diari", start) and bool(
        _RE_NOUN_DETERMINER_BEFORE.search(folded[:start])
    )


def has_recurrence_keyword(folded: str) -> bool:
    """¿Hay una palabra de repetición (todos los / cada / diario / semanal / mensual...)?

    "diario" precedido de mi/mis/el/un/del/su/tu es un sustantivo y no cuenta.
    """
    return any(
        not is_noun_diario(folded, m.start()) for m in RE_RECURRENCE_KEYWORD.finditer(folded)
    )


_RE_PAST_LEFTOVER = re.compile(r"\b(?:pasad[oa]|anterior|hace)\b")


def _resolve_marked(hour: int, minute: int, marker: str) -> time | str:
    """Hora con marcador explícito (am/pm o periodo del día)."""
    if marker in ("am", "pm"):
        if not 1 <= hour <= 12:
            return "invalid_time"
        if marker == "am" and hour == 12:
            return "ambiguous_time"  # ¿medianoche de hoy o de mañana?
        return time(hour % 12 + (12 if marker == "pm" else 0), minute)
    if not 1 <= hour <= 12:
        return "invalid_time"
    if marker == "manana":
        return time(hour, minute)  # 12 de la mañana = mediodía
    if marker == "tarde":
        return time(12 if hour == 12 else hour + 12, minute)
    if marker == "noche":
        return time(hour + 12, minute) if 6 <= hour <= 11 else "ambiguous_time"
    return time(hour, minute) if 1 <= hour <= 6 else "ambiguous_time"  # madrugada


def _resolve_clock(
    hour: int, minute: int, marker: str | None, literal24: bool, ask_range: tuple[int, int]
) -> tuple[time | str, bool]:
    """Convierte (hora, minuto, marcador) a `time`, o a la razón para preguntar.

    Devuelve también si el am/pm se asumió. Reglas:
    - Con marcador (am/pm, "de la tarde"...): se respeta.
    - 13-23, 0 y las horas con cero inicial (`08:30`): reloj de 24 h.
    - 12 sin marcador: mediodía.
    - 1 a 4 sin marcador: tarde (asumido, `inferred`).
    - 5 a 11 sin marcador (rango `ask_range`): "ambiguous_meridiem", se pregunta.
    """
    if marker is not None:
        return _resolve_marked(hour, minute, marker), False
    if hour > 23:
        return "invalid_time", False
    if hour >= 13 or hour == 0 or literal24 or hour == 12:
        return time(hour, minute), False
    low, high = ask_range
    if low <= hour <= high:
        return "ambiguous_meridiem", False
    if hour < low:
        return time(hour + 12, minute), True
    return time(hour, minute), True


_RE_DOTTED = re.compile(r"(?<![\d.])(?:[01]?\d|2[0-3])\.[0-5]\d(?![\d.])")
_RE_A_LAS_BEFORE = re.compile(r"\ba\s+las?\s+$")
_RE_NUMBER_AFTER = re.compile(r"\A\s+\d{1,3}\b(?![.:/]\d)")


def has_dotted_time(work: str, has_day: bool) -> bool:
    """¿Hay un "7.30"? Parece hora (con un día o tras "a las") pero no se entiende: se pregunta."""
    return any(
        has_day or _RE_A_LAS_BEFORE.search(work[: m.start()]) for m in _RE_DOTTED.finditer(work)
    )


def number_after_day(folded: str, work: str, ends: list[int]) -> bool:
    """¿Queda un número suelto pegado tras un día ("mañana 7 dentista")? Puede ser una hora.

    `folded` es el texto sin enmascarar los días/horas; `work`, con lo reconocido en blanco;
    `ends` son los finales de los días. Pegado = solo espacios entre el día y el número, así
    "el viernes a las 5 pm 2 cosas" no cuenta (el número va tras la hora, no tras el día).
    """
    for end in ends:
        gap = re.match(r"\s+(?=\d)", folded[end:])
        if gap and _RE_NUMBER_AFTER.match(work[end:]) and work[end + gap.end()].isdigit():
            return True
    return False


def _minutes_of(token: str) -> int | None:
    """ "15" / "cuarto" / "media" / "cinco" -> minutos; None si no es un minuto válido (> 59)."""
    value = int(token) if token.isdigit() else _MINUTE_WORDS[token]
    return value if value <= 59 else None


def _mask(work: str, start: int, end: int) -> str:
    return work[:start] + " " * (end - start) + work[end:]


def scan_times(
    work: str, ask_range: tuple[int, int] = DEFAULT_MERIDIEM_ASK_RANGE
) -> tuple[list[Hit], list[Hit], str]:
    """Busca horas en texto plegado. Devuelve (fuertes, débiles, texto con lo fuerte enmascarado).

    Una hora "débil" es `H:MM` suelto (p. ej. un versículo "3:16"): solo cuenta si el texto
    trae también un día; quien llama decide.
    """
    strong: list[Hit] = []
    weak: list[Hit] = []

    def take(
        match: re.Match[str], hour: int, minute: int, resolved: tuple[time | str, bool]
    ) -> None:
        nonlocal work
        value, inferred = resolved
        strong.append(Hit(match.start(), match.end(), "time", value, inferred, (hour, minute)))
        work = _mask(work, match.start(), match.end())

    for m in list(_RE_CLOCK.finditer(work)):
        prefixed = m["hw"] is not None
        hour_text = m["hw"] or m["hd"]
        hour = int(hour_text) if hour_text.isdigit() else _HOUR_WORDS[hour_text]
        marker = m["per"] or (m["ap"] + "m" if m["ap"] else None)
        if not (prefixed or m["m"] or marker):
            continue  # un número suelto no es hora ("mañana 7 dentista": lo pregunta quien llama)
        if not prefixed and m["m"] is None and (m["plus"] or m["minus"]):
            continue
        minute = int(m["m"] or 0)
        if m["plus"]:
            extra = _minutes_of(m["plus"])
            minute += extra if extra is not None else 99
        elif m["minus"]:
            extra = _minutes_of(m["minus"])
            if extra is None or not 1 <= extra <= 59:
                minute = 99
            else:
                hour = 12 if hour == 1 else hour - 1 if hour >= 2 else 23
                minute = 60 - extra
        if minute > 59:
            take(m, hour, 0, ("invalid_time", False))
            continue
        literal24 = prefixed is False and len(hour_text) == 2 and hour_text[0] == "0"
        resolved = _resolve_clock(hour, minute, marker, literal24, ask_range)
        if not prefixed and marker is None and not (hour >= 13 or literal24):
            weak.append(Hit(m.start(), m.end(), "time", *resolved, (hour, minute)))
            continue
        take(m, hour, minute, resolved)
    for m in list(_RE_NOON.finditer(work)):
        take(m, 12, 0, (time(12, 0), False))
    for m in list(_RE_MIDNIGHT.finditer(work)):
        take(m, 0, 0, ("ambiguous_time", False))
    return strong, weak, work


# --- Días ----------------------------------------------------------------------------------

_MONTH_ALT = "|".join(_MONTHS)
_WEEKDAY_ALT = "|".join(WEEKDAYS)
_RE_RELATIVE = re.compile(
    r"\b(?:en|dentro\s+de)\s+(?P<n>\d{1,3}|" + "|".join(_NUMBER_WORDS) + r"|media)\s+"
    r"(?P<u>minutos?|min|horas?|hrs?|dias?|semanas?)\b"
)
_RE_DAY_AFTER = re.compile(r"(?:\bpara\s+)?\bpasado\s+manana\b")
_RE_PAST_WORD = re.compile(r"\b(?P<w>ayer|anteayer|antier)\b")
_RE_DATE_TEXT = re.compile(
    r"(?:\bpara\s+)?(?:\bel\s+)?(?<![\d/])(?P<d>\d{1,2})\s+de\s+(?P<mon>" + _MONTH_ALT + r")\b"
    r"(?:\s+(?:de|del)\s+(?P<y>\d{4}))?"
)
_RE_DATE_NUM_EL = re.compile(
    r"(?:\bpara\s+)?\bel\s+(?<![\d/])(?P<d>\d{1,2})/(?P<mon>\d{1,2})(?:/(?P<y>\d{4}|\d{2}))?(?![\d/])"
)
_RE_DATE_NUM_YEAR = re.compile(
    r"(?<![\d/])(?P<d>\d{1,2})/(?P<mon>\d{1,2})/(?P<y>\d{4}|\d{2})(?![\d/])"
)
_RE_TODAY = re.compile(r"(?:\bpara\s+)?\bhoy\b")
_RE_TOMORROW = re.compile(r"(?:\bpara\s+)?\b(?P<w>manana)\b")
_RE_WEEKDAY = re.compile(
    r"(?:\bpara\s+)?(?:\b(?P<art>el)\s+)?(?:\b(?P<mod>este|esta|proximo)\s+)?\b(?P<wd>"
    + _WEEKDAY_ALT
    + r")\b"
    r"(?P<qv>\s+que\s+viene)?"
)
_RE_ARTICLE_BEFORE = re.compile(r"\b(?:la|las|esta|cada|toda)\s+$")


# Fechas con aspecto de fecha que la gramática cerrada NO entiende: se pregunta (unsupported_date).
_ORDINAL = r"\d{1,2}(?:ro|er|ero|do|to|mo|vo|no|º|°|ª)"
_RE_UNSUPPORTED = re.compile(
    r"(?:\bpara\s+)?(?:\bel\s+)?\b(?:" + _ORDINAL + r"|primero)\s+de\s+(?:" + _MONTH_ALT + r")\b"
    r"|(?:\bpara\s+)?(?:\bel\s+)?\b\d{1,2}\s+(?:de\s+(?:este|esta|ese|el|la|lo|proximo|siguiente)"
    r"|del)\s+(?:proximo\s+)?(?:mes|ano|semana)(?:\s+(?:que\s+viene|proximo|siguiente))?\b"
    r"|\b(?:en|dentro\s+de)\s+(?:\d{1,3}|" + "|".join(_NUMBER_WORDS) + r"|media?)\s+"
    r"(?:mes(?:es)?|anos?|trimestres?|quincenas?)\b"
    r"|\bfin\s+de\s+(?:mes|ano|semana)\b"
    r"|\b(?:este|esta|ese|esa|proximo|proxima|siguiente|pasado|pasada)\s+(?:mes|ano|semana)\b"
    r"|\b(?:el\s+|la\s+)?(?:mes|ano|semana)\s+(?:que\s+viene|proximo|proxima|siguiente)\b"
)
# "el N" = el día N del mes (la siguiente ocurrencia; hoy cuenta). Solo si lo que sigue no es una
# palabra ("el 5 a las 3", "pagar el 5."): "el 3 de espadas" o "el 5 dentista" se preguntan.
_RE_DAY_OF_MONTH = re.compile(
    r"(?:\bpara\s+)?\bel\s+(?P<d>\d{1,2})\b(?![/:.]\d)"
    r"(?=\s*(?:$|[,.;!?)]|\ba\s+las?\b|\d{1,2}\s*(?:[ap]\s*\.?\s*m\b|:\d)))"
)
_RE_EL_NUMBER_LEFTOVER = re.compile(r"\bel\s+\d{1,2}\b(?![/:.]\d)")


def _next_day_of_month(day_number: int, today: date) -> date | None:
    """El próximo día `day_number` del mes, desde `today` (hoy cuenta). Salta meses sin ese día."""
    year, month = today.year, today.month
    for _ in range(14):
        try:
            candidate = date(year, month, day_number)
        except ValueError:
            candidate = None
        if candidate is not None and candidate >= today:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def _resolve_date(
    day: int, month: int, year: int | None, today: date
) -> tuple[date | None, str | None]:
    """Día/mes[/año] -> fecha. Sin año: la siguiente ocurrencia (hoy cuenta)."""
    if not 1 <= month <= 12:
        return None, "invalid_date"
    if year is not None:
        if year < 100:
            year += 2000
        try:
            return date(year, month, day), None
        except ValueError:
            return None, "invalid_date"
    for candidate_year in range(today.year, today.year + _MAX_YEARS_AHEAD + 1):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate, None
    return None, "invalid_date"


_RE_A_OR_CON_BEFORE = re.compile(r"\b(?:a|con)\s+$")
_RE_PRONOUN_AFTER = re.compile(r"\A\s+(?:me|te|le|nos|les|se)\b")


def _is_ambiguous_domingo(match: re.Match[str], original: str, work: str) -> bool:
    """¿"domingo" es quizá un nombre propio y no el día? Entonces no se decide: se pregunta.

    Solo aplica a "domingo" SIN determinante (`el / este / esta / próximo / que viene`), y solo si:
    (a) va tras "a" o "con" ("llamar a domingo"), con cualquier capitalización;
    (b) tiene mayúscula inicial a mitad de frase ("regalo para Domingo");
    (c) está al inicio seguido de me/te/le/nos/les/se ("Domingo me presta el carro").
    Un texto todo en mayúsculas se evalúa como si fuera minúscula (la capitalización no informa).
    En cualquier otro caso es la fecha ("ensayo domingo 5pm", "Domingo ensayo 5pm").
    """
    if match["wd"] != "domingo" or match["art"] or match["mod"] or match["qv"]:
        return False
    start, end = match.start("wd"), match.end("wd")
    before = work[:start]
    if _RE_A_OR_CON_BEFORE.search(before):
        return True
    has_lowercase = any(ch.islower() for ch in original)
    if has_lowercase and original[start].isupper() and before.strip():
        return True
    return not before.strip() and bool(_RE_PRONOUN_AFTER.match(work[end:]))


def _scan_days(work: str, original: str, today: date) -> tuple[list[Hit], str, bool]:
    """Busca expresiones de día. `value` = (fecha | None, razón | None, extra).

    El tercer valor indica si se descartó un "Domingo" por ser nombre propio.
    """
    hits: list[Hit] = []
    skipped_name = False

    def take(match: re.Match[str], kind: str, value: object) -> None:
        nonlocal work
        hits.append(Hit(match.start(), match.end(), kind, value))
        work = _mask(work, match.start(), match.end())

    for m in list(_RE_UNSUPPORTED.finditer(work)):
        take(m, "unsupported", "unsupported_date")
    for m in list(_RE_RELATIVE.finditer(work)):
        amount = m["n"]
        unit = m["u"]
        if amount == "media":
            if not unit.startswith("hora"):
                take(m, "invalid", "invalid_date")
                continue
            take(m, "instant", timedelta(minutes=30))
            continue
        count = int(amount) if amount.isdigit() else _NUMBER_WORDS[amount]
        if unit.startswith(("min",)):
            take(m, "instant", timedelta(minutes=count))
        elif unit.startswith(("hora", "hr")):
            take(m, "instant", timedelta(hours=count))
        elif unit.startswith("dia"):
            take(m, "day", (today + timedelta(days=count), None, None))
        else:
            take(m, "day", (today + timedelta(weeks=count), None, None))
    for m in list(_RE_DAY_AFTER.finditer(work)):
        take(m, "day", (today + timedelta(days=2), None, None))
    for m in list(_RE_PAST_WORD.finditer(work)):
        back = 1 if m["w"] == "ayer" else 2
        take(m, "day", (today - timedelta(days=back), None, None))
    for m in list(_RE_DATE_TEXT.finditer(work)):
        found, reason = _resolve_date(
            int(m["d"]), _MONTHS[m["mon"]], int(m["y"]) if m["y"] else None, today
        )
        take(m, "day", (found, reason, "yearless" if not m["y"] else None))
    for pattern in (_RE_DATE_NUM_EL, _RE_DATE_NUM_YEAR):
        for m in list(pattern.finditer(work)):
            found, reason = _resolve_date(
                int(m["d"]), int(m["mon"]), int(m["y"]) if m["y"] else None, today
            )
            take(m, "day", (found, reason, "yearless" if not m["y"] else None))
    for m in list(_RE_DAY_OF_MONTH.finditer(work)):
        day_number = int(m["d"])
        found = _next_day_of_month(day_number, today) if 1 <= day_number <= 31 else None
        if found is None:
            take(m, "invalid", "invalid_date")
        else:
            take(m, "day", (found, None, "monthday"))
    for m in list(_RE_TODAY.finditer(work)):
        take(m, "day", (today, None, "today"))
    for m in list(_RE_TOMORROW.finditer(work)):
        if _RE_ARTICLE_BEFORE.search(work[: m.start("w")]):
            continue  # "de la mañana": es parte del día, no el día de mañana
        take(m, "day", (today + timedelta(days=1), None, "tomorrow"))
    for m in list(_RE_WEEKDAY.finditer(work)):
        if _is_ambiguous_domingo(m, original, work):
            skipped_name = True  # "llamar a Domingo": ¿nombre o día?
            continue
        weekday = WEEKDAYS.index(m["wd"])
        delta = (weekday - today.weekday()) % 7
        if delta == 0:
            if m["mod"] in ("este", "esta"):
                take(m, "day", (today, None, "weekday"))
            elif m["mod"] == "proximo" or m["qv"]:
                take(m, "day", (today + timedelta(days=7), None, "weekday"))
            else:
                take(m, "day", (None, "same_weekday", "weekday"))
        else:
            take(m, "day", (today + timedelta(days=delta), None, "weekday"))
    for m in list(
        _RE_EL_NUMBER_LEFTOVER.finditer(work)
    ):  # "el 5 dentista": parece fecha, no se entiende
        take(m, "unsupported", "unsupported_date")
    return hits, work, skipped_name


# --- API pública ---------------------------------------------------------------------------


def clean_title(original: str, spans: list[tuple[int, int]]) -> str:
    """Quita del texto original los trozos reconocidos y las palabras sueltas que quedan pegadas."""
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        pieces.append(original[cursor:start])
        cursor = max(cursor, end)
    pieces.append(original[cursor:])
    words = " ".join("".join(pieces).split()).strip(" ,;:.-").split(" ")
    while words and fold(words[0]) in _GLUE_WORDS:
        words.pop(0)
    while words and fold(words[-1]) in _GLUE_WORDS:
        words.pop()
    return " ".join(words).strip(" ,;:.-")


def strip_reminder_verb(title: str) -> str:
    """ "recordar llevar tarea" -> "llevar tarea". Solo al inicio y si queda algo después."""
    words = title.split()
    if len(words) > 1 and fold(words[0]) in _REMINDER_VERBS:
        words = words[1:]
        if len(words) > 1 and fold(words[0]) in {"que", "de"}:
            words = words[1:]
        return " ".join(words)
    return title


def _ask(title: str, reason: str, candidates: tuple[datetime, ...] = ()) -> WhenResult:
    return WhenResult("ask", title, reason=reason, candidates=candidates)


def parse_when(
    text: str,
    now: Clock,
    tz_name: str,
    default_morning: time,
    meridiem_ask_range: tuple[int, int] = DEFAULT_MERIDIEM_ASK_RANGE,
) -> WhenResult:
    """Interpreta la fecha/hora de `text` en la zona `tz_name`, con el reloj inyectado.

    `meridiem_ask_range` = horas sin am/pm que se preguntan (ver `_resolve_clock`).
    """
    low, high = meridiem_ask_range
    if not 1 <= low <= high <= 11:
        raise ValueError("El rango de horas a preguntar debe cumplir 1 <= bajo <= alto <= 11")
    moment = now()
    today = to_local(moment, tz_name).date()
    original = text
    folded, verse_doubt = mask_citations(fold(text))

    days, work, skipped_name = _scan_days(folded, original, today)
    strong, weak, work = scan_times(work, meridiem_ask_range)
    for hit in weak:
        work = _mask(work, hit.start, hit.end)
    if days:  # una hora débil ("8:30") solo cuenta si hay un día en el texto
        usable, doubtful = split_doubtful_weak(original, weak)
        verse_doubt = verse_doubt or doubtful
        strong.extend(usable)
    hits = days + strong
    dotted = has_dotted_time(work, bool(days))
    if has_recurrence_keyword(folded):  # "cada mes", "semanal": nunca un aviso único
        spans = [(h.start, h.end) for h in hits]
        return _ask(strip_reminder_verb(clean_title(original, spans)), "unrecognized_recurrence")
    if skipped_name and not days:  # ¿Domingo es una persona o el día? Nunca se asume "hoy"
        title = strip_reminder_verb(clean_title(original, [(h.start, h.end) for h in hits]))
        return _ask(title, "name_or_day")
    if not hits:
        if verse_doubt:
            return _ask(clean_title(original, []), "time_or_verse")
        if dotted:
            return _ask(clean_title(original, []), "dotted_time")
        return WhenResult("none", clean_title(original, []))

    title = strip_reminder_verb(clean_title(original, [(h.start, h.end) for h in hits]))
    if verse_doubt:
        return _ask(title, "time_or_verse")
    if dotted:
        return _ask(title, "dotted_time")
    if number_after_day(folded, work, [h.end for h in days if h.kind == "day"]):
        return _ask(title, "number_after_day")
    instants = [h for h in days if h.kind == "instant"]
    plain_days = [h for h in days if h.kind == "day"]
    if any(h.kind == "invalid" for h in days):
        return _ask(title, "invalid_date")
    if any(h.kind == "unsupported" for h in days):
        return _ask(title, "unsupported_date")
    if (
        len(plain_days) > 1
        or len(strong) > 1
        or len(instants) > 1
        or (instants and (plain_days or strong))
    ):
        return _ask(title, "two_dates")
    meridiem_hit = next((h for h in strong if h.value == "ambiguous_meridiem"), None)
    for hit in strong:
        if isinstance(hit.value, str) and hit is not meridiem_hit:
            if hit.value == "ambiguous_time" and hit.raw is not None and hit.raw[0] in (0, 12):
                day_hit = plain_days[0].value if len(plain_days) == 1 else (today, None, None)
                assert isinstance(day_hit, tuple)
                options = _midnight_options(day_hit[0], hit.raw[1], tz_name, moment)
                return _ask(title, "ambiguous_time", options)
            return _ask(title, hit.value)
    if RE_TIME_LEFTOVER.search(work):
        return _ask(title, "unrecognized_time")
    if _RE_PAST_LEFTOVER.search(work):
        return _ask(title, "past")  # "el viernes pasado": no se adivina hacia atrás

    if instants:
        delta = instants[0].value
        assert isinstance(delta, timedelta)
        when = moment.replace(second=0, microsecond=0) + delta
        return WhenResult("ok", title, when_utc=when, has_time=True)

    if meridiem_hit is not None:
        assert meridiem_hit.raw is not None
        clock = time(*meridiem_hit.raw)  # lectura de la mañana; la de la tarde se arma abajo
    else:
        clock = strong[0].value if strong else default_morning
    assert isinstance(clock, time)
    has_time = bool(strong)
    day_value = plain_days[0].value if plain_days else (today, None, "time_only")
    assert isinstance(day_value, tuple)
    day, reason, extra = day_value
    if reason == "same_weekday" and meridiem_hit is not None:
        return _ask(title, "same_weekday")  # primero el día; la hora se pregunta después
    if reason == "same_weekday":
        options = tuple(
            when
            for when in (
                local_to_utc(datetime.combine(today, clock), tz_name),
                local_to_utc(datetime.combine(today + timedelta(days=7), clock), tz_name),
            )
            if when > moment
        )
        return _ask(title, "same_weekday", options)
    if reason is not None:
        return _ask(title, reason)
    assert isinstance(day, date)

    if extra == "tomorrow" and to_local(moment, tz_name).hour < _SMALL_HOURS_END:
        # Regla 10: pasada la medianoche "mañana" puede ser hoy ("mañana a las 8" a las 00:40)
        if meridiem_hit is not None:
            return _ask(title, "today_or_tomorrow")  # primero el día; la hora se pregunta después
        today_at = local_to_utc(datetime.combine(today, clock), tz_name)
        if today_at > moment:
            tomorrow_at = local_to_utc(datetime.combine(day, clock), tz_name)
            return _ask(title, "today_or_tomorrow", (today_at, tomorrow_at))
    if not plain_days and strong and strong[0].raw is not None and strong[0].raw[0] <= 11:
        if meridiem_hit is not None or strong[0].inferred:
            # Regla 9: sin día, la próxima ocurrencia futura de CADA lectura (am y pm). Si la am
            # llega antes que la pm (o es una hora de 5 a 11), se pregunta con las dos.
            hour, minute = strong[0].raw
            readings = (time(hour, minute), time(hour + 12, minute))
            am_next, pm_next = (
                _next_local(reading, today, tz_name, moment) for reading in readings
            )
            if meridiem_hit is not None or am_next < pm_next:
                return _ask(title, "ambiguous_meridiem", tuple(sorted((am_next, pm_next))))

    if meridiem_hit is not None:
        readings = (clock, clock.replace(hour=clock.hour + 12))
        options = tuple(
            option
            for option in (
                local_to_utc(datetime.combine(day, reading), tz_name) for reading in readings
            )
            if option > moment
        )
        if options:
            return _ask(title, "ambiguous_meridiem", options)
        return _ask(title, "past", _future_alternatives(day, clock, extra, tz_name, moment))
    when = local_to_utc(datetime.combine(day, clock), tz_name)
    if when <= moment:
        return _ask(title, "past", _future_alternatives(day, clock, extra, tz_name, moment))
    return WhenResult(
        "ok",
        title,
        when_utc=when,
        has_time=has_time,
        meridiem_inferred=bool(strong) and strong[0].inferred,
    )


def _next_local(clock: time, today: date, tz_name: str, moment: datetime) -> datetime:
    """La próxima vez (UTC) que el reloj local marca `clock`: hoy si aún no pasó, si no mañana."""
    first = local_to_utc(datetime.combine(today, clock), tz_name)
    if first > moment:
        return first
    return local_to_utc(datetime.combine(today + timedelta(days=1), clock), tz_name)


def _midnight_options(
    day: date | None, minute: int, tz_name: str, moment: datetime
) -> tuple[datetime, ...]:
    """ "12 am" / "medianoche": ¿la de ese día (00:00) o la del día siguiente? Solo las futuras."""
    if day is None:
        return ()
    clock = time(0, minute)
    options = (
        local_to_utc(datetime.combine(day, clock), tz_name),
        local_to_utc(datetime.combine(day + timedelta(days=1), clock), tz_name),
    )
    return tuple(option for option in options if option > moment)


def _future_alternatives(
    day: date, clock: time, extra: str | None, tz_name: str, moment: datetime
) -> tuple[datetime, ...]:
    """Qué ofrecer cuando la fecha ya pasó: la siguiente ocurrencia natural."""
    if extra in ("today", "time_only"):
        later = day + timedelta(days=1)
    elif extra == "weekday":
        later = day + timedelta(days=7)
    elif extra == "yearless":  # la siguiente ocurrencia REAL (29 de febrero -> próximo bisiesto)
        later = _resolve_date(day.day, day.month, None, day + timedelta(days=1))[0]
    elif extra == "monthday":
        later = _next_day_of_month(day.day, day + timedelta(days=1))
    else:
        return ()
    if later is None:
        return ()
    candidate = local_to_utc(datetime.combine(later, clock), tz_name)
    return (candidate,) if candidate > moment else ()


def format_when(moment_utc: datetime, tz_name: str, now: Clock) -> str:
    """ "domingo 4 de octubre, 8:00 am": día de la semana siempre y am/pm explícito."""
    local = to_local(moment_utc, tz_name)
    suffix = "am" if local.hour < 12 else "pm"
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {suffix}"
    year = "" if local.year == to_local(now(), tz_name).year else f" de {local.year}"
    weekday = WEEKDAY_NAMES_ES[local.weekday()]
    return f"{weekday} {local.day} de {MONTH_NAMES_ES[local.month - 1]}{year}, {clock}"
