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

Status = Literal["none", "ok", "ask"]


@dataclass(frozen=True)
class WhenResult:
    """Resultado de interpretar la fecha de un texto.

    - `none`: no hay fecha en el texto.
    - `ok`: fecha resuelta (`when_utc`); `has_time=False` si se usó la hora por defecto.
    - `ask`: hay que preguntar; `reason` dice por qué y `candidates` son opciones futuras.
    """

    status: Status
    title: str
    when_utc: datetime | None = None
    has_time: bool = False
    reason: str | None = None
    candidates: tuple[datetime, ...] = ()


@dataclass
class Hit:
    """Un trozo reconocido: posición en el texto, tipo y valor."""

    start: int
    end: int
    kind: str
    value: object


def fold(text: str) -> str:
    """Minúsculas y sin acentos, conservando el largo (1 carácter -> 1 carácter)."""
    return "".join(unicodedata.normalize("NFD", ch)[0].lower()[:1] for ch in text)


# --- Horas ---------------------------------------------------------------------------------

_RE_PERIOD_TIME = re.compile(
    r"(?:\ba\s+las?\s+)?(?<![\d:])(?P<h>\d{1,2})(?::(?P<m>[0-5]\d))?\s*"
    r"(?:de|por|en)\s+la\s+(?P<per>manana|tarde|noche|madrugada)\b"
)
_RE_AMPM = re.compile(
    r"(?:\ba\s+las?\s+)?(?<![\d:])(?P<h>\d{1,2})(?::(?P<m>[0-5]\d))?\s*(?P<ap>[ap])\.?m\b\.?"
)
_RE_COLON = re.compile(r"(?P<pre>\ba\s+las?\s+)?(?<![\d:])(?P<h>\d{1,2}):(?P<m>[0-5]\d)(?![\d:])")
_RE_A_LAS = re.compile(r"\ba\s+las?\s+(?P<h>\d{1,2})\b(?:\s+y\s+(?P<q>media|cuarto)\b)?(?!:)")
_RE_NOON = re.compile(r"\b(?:a\s+|al\s+)?mediodia\b")
# Restos que parecen una hora pero no se entendieron: ante la duda se pregunta.
RE_TIME_LEFTOVER = re.compile(
    r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*[ap]\.?m\b|\bmedianoche\b|\ba\s+las?\s+\d"
    r"|\b(?:de|por|en)\s+la\s+(?:manana|tarde|noche|madrugada)\b"
    r"|\besta\s+(?:manana|tarde|noche)\b|\by\s+(?:media|cuarto)\b|\bmenos\s+(?:cuarto|\d)"
)
_RE_PAST_LEFTOVER = re.compile(r"\b(?:pasad[oa]|anterior|hace)\b")


def _resolve_clock(hour: int, minute: int, marker: str | None, literal24: bool) -> time | str:
    """Convierte (hora, minuto, marcador) a `time`, o devuelve la razón para preguntar.

    Sin marcador: 13-23 y 0 son de 24 h; 12 es mediodía; 7-11 son de la mañana; 1-6 de la tarde.
    """
    if marker in ("am", "pm"):
        if not 1 <= hour <= 12:
            return "invalid_time"
        if marker == "am" and hour == 12:
            return "ambiguous_time"  # ¿medianoche de hoy o de mañana?
        return time(hour % 12 + (12 if marker == "pm" else 0), minute)
    if marker is not None:  # periodo del día
        if not 1 <= hour <= 12:
            return "invalid_time"
        if marker == "manana":
            return time(hour, minute)  # 12 de la mañana = mediodía
        if marker == "tarde":
            return time(12 if hour == 12 else hour + 12, minute)
        if marker == "noche":
            return time(hour + 12, minute) if 6 <= hour <= 11 else "ambiguous_time"
        return time(hour, minute) if 1 <= hour <= 6 else "ambiguous_time"  # madrugada
    if hour > 23:
        return "invalid_time"
    if hour >= 7 or hour == 0 or literal24:
        return time(hour, minute)
    return time(hour + 12, minute)


def _mask(work: str, start: int, end: int) -> str:
    return work[:start] + " " * (end - start) + work[end:]


def scan_times(work: str) -> tuple[list[Hit], list[Hit], str]:
    """Busca horas en texto plegado. Devuelve (fuertes, débiles, texto con lo fuerte enmascarado).

    Una hora "débil" es `H:MM` suelto (p. ej. un versículo "3:16"): solo cuenta si el texto
    trae también un día; quien llama decide.
    """
    strong: list[Hit] = []
    weak: list[Hit] = []

    def take(match: re.Match[str], value: time | str) -> None:
        nonlocal work
        strong.append(Hit(match.start(), match.end(), "time", value))
        work = _mask(work, match.start(), match.end())

    for m in list(_RE_PERIOD_TIME.finditer(work)):
        take(m, _resolve_clock(int(m["h"]), int(m["m"] or 0), m["per"], False))
    for m in list(_RE_AMPM.finditer(work)):
        take(m, _resolve_clock(int(m["h"]), int(m["m"] or 0), m["ap"] + "m", False))
    for m in list(_RE_COLON.finditer(work)):
        hour_text = m["h"]
        literal24 = len(hour_text) == 2 and hour_text[0] == "0"
        value = _resolve_clock(int(hour_text), int(m["m"]), None, literal24)
        if m["pre"] or int(hour_text) >= 13 or literal24:
            take(m, value)
        else:
            weak.append(Hit(m.start(), m.end(), "time", value))
    for m in list(_RE_A_LAS.finditer(work)):
        minute = {"media": 30, "cuarto": 15}.get(m["q"] or "", 0)
        take(m, _resolve_clock(int(m["h"]), minute, None, False))
    for m in list(_RE_NOON.finditer(work)):
        take(m, time(12, 0))
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
    r"(?:\bpara\s+)?(?:\bel\s+)?(?:\b(?P<mod>este|proximo)\s+)?\b(?P<wd>" + _WEEKDAY_ALT + r")\b"
    r"(?P<qv>\s+que\s+viene)?"
)
_RE_ARTICLE_BEFORE = re.compile(r"\b(?:la|las|esta|cada|toda)\s+$")


def _add_years(day: date, years: int) -> date | None:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
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


def _scan_days(work: str, original: str, today: date) -> tuple[list[Hit], str]:
    """Busca expresiones de día. `value` = (fecha | None, razón | None, extra)."""
    hits: list[Hit] = []

    def take(match: re.Match[str], kind: str, value: object) -> None:
        nonlocal work
        hits.append(Hit(match.start(), match.end(), kind, value))
        work = _mask(work, match.start(), match.end())

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
    for m in list(_RE_TODAY.finditer(work)):
        take(m, "day", (today, None, "today"))
    for m in list(_RE_TOMORROW.finditer(work)):
        if _RE_ARTICLE_BEFORE.search(work[: m.start("w")]):
            continue  # "de la mañana": es parte del día, no el día de mañana
        take(m, "day", (today + timedelta(days=1), None, None))
    for m in list(_RE_WEEKDAY.finditer(work)):
        if original[m.start("wd")].isupper() and m.start("wd") > 0:
            continue  # "llamar a Domingo": nombre propio
        weekday = WEEKDAYS.index(m["wd"])
        delta = (weekday - today.weekday()) % 7
        if delta == 0:
            if m["mod"] == "este":
                take(m, "day", (today, None, "weekday"))
            elif m["mod"] == "proximo" or m["qv"]:
                take(m, "day", (today + timedelta(days=7), None, "weekday"))
            else:
                take(m, "day", (None, "same_weekday", "weekday"))
        else:
            take(m, "day", (today + timedelta(days=delta), None, "weekday"))
    return hits, work


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


def _ask(title: str, reason: str, candidates: tuple[datetime, ...] = ()) -> WhenResult:
    return WhenResult("ask", title, reason=reason, candidates=candidates)


def parse_when(text: str, now: Clock, tz_name: str, default_morning: time) -> WhenResult:
    """Interpreta la fecha/hora de `text` en la zona `tz_name`, con el reloj inyectado."""
    moment = now()
    today = to_local(moment, tz_name).date()
    original = text
    folded = fold(text)

    days, work = _scan_days(folded, original, today)
    strong, weak, work = scan_times(work)
    if days:  # una hora débil ("8:30") solo cuenta si hay un día en el texto
        for hit in weak:
            strong.append(hit)
            work = _mask(work, hit.start, hit.end)
    else:
        for hit in weak:
            work = _mask(work, hit.start, hit.end)
    hits = days + strong
    if not hits:
        return WhenResult("none", clean_title(original, []))

    title = clean_title(original, [(h.start, h.end) for h in hits])
    instants = [h for h in days if h.kind == "instant"]
    plain_days = [h for h in days if h.kind == "day"]
    if any(h.kind == "invalid" for h in days):
        return _ask(title, "invalid_date")
    if (
        len(plain_days) > 1
        or len(strong) > 1
        or len(instants) > 1
        or (instants and (plain_days or strong))
    ):
        return _ask(title, "two_dates")
    for hit in strong:
        if isinstance(hit.value, str):
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

    clock = strong[0].value if strong else default_morning
    assert isinstance(clock, time)
    has_time = bool(strong)
    day_value = plain_days[0].value if plain_days else (today, None, "time_only")
    assert isinstance(day_value, tuple)
    day, reason, extra = day_value
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

    when = local_to_utc(datetime.combine(day, clock), tz_name)
    if when <= moment:
        return _ask(title, "past", _future_alternatives(day, clock, extra, tz_name, moment))
    return WhenResult("ok", title, when_utc=when, has_time=has_time)


def _future_alternatives(
    day: date, clock: time, extra: str | None, tz_name: str, moment: datetime
) -> tuple[datetime, ...]:
    """Qué ofrecer cuando la fecha ya pasó: la siguiente ocurrencia natural."""
    if extra in ("today", "time_only"):
        later = day + timedelta(days=1)
    elif extra == "weekday":
        later = day + timedelta(days=7)
    elif extra == "yearless":
        later = _add_years(day, 1) or day + timedelta(days=365)
    else:
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
