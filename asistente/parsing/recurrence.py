"""Recordatorios repetidos: lista CERRADA de expresiones -> regla `rrule` (RFC 5545).

Se entiende solo:
    "todos los días [hora]" / "cada día [hora]" / "diario [hora]"
    "cada <día de la semana> [hora]" / "todos los <días de la semana> [hora]"
    "de lunes a viernes [hora]"
Cualquier otra cosa no se interpreta (el handler pregunta); una palabra de repetición
("cada mes", "semanal") que no encaje NUNCA se guarda como aviso único.
La hora usa las mismas reglas que `parsing/dates.py`. `next_occurrence` es la función que
también usa el motor de recordatorios: calcula desde la hora PROGRAMADA (no desde `now`) y
respeta el horario de verano. `parse_schedule` es el flujo del handler: primero la repetición,
luego la fecha suelta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Literal

from dateutil.rrule import rrulestr

from asistente.parsing.dates import (
    DEFAULT_MERIDIEM_ASK_RANGE,
    RE_RECURRENCE_KEYWORD,
    RE_TIME_LEFTOVER,
    WEEKDAYS,
    WhenResult,
    clean_title,
    fold,
    has_dotted_time,
    mask_citations,
    number_after_day,
    parse_when,
    scan_times,
    split_doubtful_weak,
    strip_reminder_verb,
)
from asistente.timeutil import Clock, local_to_utc, to_local

_RRULE_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")  # mismo orden que WEEKDAYS
_RE_DAILY = re.compile(r"\b(?:todos\s+los\s+dias|cada\s+dia|diari[oa])\b")
_RE_EVERY_WEEKDAY = re.compile(
    r"\b(?:cada|todos\s+los)\s+(?P<wd>" + "|".join(WEEKDAYS) + r")(?:s)?\b"  # "todos los lunes"
)
_RE_WORKDAYS = re.compile(r"\bde\s+lunes\s+a\s+viernes\b")


@dataclass(frozen=True)
class RecurrenceResult:
    """`none`: no hay repetición; `ok`: regla y primera ocurrencia futura; `ask`: preguntar."""

    status: Literal["none", "ok", "ask"]
    title: str
    rrule: str | None = None
    first_at_utc: datetime | None = None
    has_time: bool = False
    reason: str | None = None
    meridiem_inferred: bool = False


def next_occurrence(
    rrule: str, scheduled_utc: datetime, after_utc: datetime, tz_name: str
) -> datetime | None:
    """Primera ocurrencia estrictamente posterior a `after_utc`, contada desde `scheduled_utc`.

    La hora del día sale de `scheduled_utc` en hora LOCAL, así "domingo 20:00" sigue siendo
    20:00 locales aunque el horario de verano cambie el UTC. Devuelve None si la serie terminó.
    """
    rule = rrulestr(rrule, dtstart=to_local(scheduled_utc, tz_name))
    found = rule.after(to_local(after_utc, tz_name), inc=False)
    return None if found is None else found.astimezone(UTC)


def parse_recurrence(
    text: str,
    now: Clock,
    tz_name: str,
    default_morning: time,
    meridiem_ask_range: tuple[int, int] = DEFAULT_MERIDIEM_ASK_RANGE,
) -> RecurrenceResult:
    folded, verse_doubt = mask_citations(fold(text))
    found: list[tuple[re.Match[str], str]] = []
    for match in _RE_DAILY.finditer(folded):
        found.append((match, "FREQ=DAILY"))
    for match in _RE_WORKDAYS.finditer(folded):
        found.append((match, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"))
    for match in _RE_EVERY_WEEKDAY.finditer(folded):
        day = _RRULE_DAYS[WEEKDAYS.index(match["wd"])]
        found.append((match, f"FREQ=WEEKLY;BYDAY={day}"))
    if not found:
        if RE_RECURRENCE_KEYWORD.search(folded):  # suena a repetición pero no es de la lista
            return RecurrenceResult(
                "ask", strip_reminder_verb(clean_title(text, [])), reason="unrecognized_recurrence"
            )
        return RecurrenceResult("none", clean_title(text, []))

    work = folded
    for match, _ in found:
        work = work[: match.start()] + " " * (match.end() - match.start()) + work[match.end() :]
    strong, weak, work = scan_times(work, meridiem_ask_range)
    for hit in weak:
        work = work[: hit.start] + " " * (hit.end - hit.start) + work[hit.end :]
    usable, doubtful = split_doubtful_weak(text, weak)
    verse_doubt = verse_doubt or doubtful
    times = strong + usable  # la repetición hace de "día": una hora suelta 8:30 sí cuenta
    spans = [(m.start(), m.end()) for m, _ in found] + [(h.start, h.end) for h in times]
    title = strip_reminder_verb(clean_title(text, spans))

    def ask(reason: str) -> RecurrenceResult:
        return RecurrenceResult("ask", title, reason=reason)

    if verse_doubt:
        return ask("time_or_verse")
    if has_dotted_time(work, True):
        return ask("dotted_time")
    if number_after_day(folded, work, [m.end() for m, _ in found]):
        return ask("number_after_day")
    if len(found) > 1 or len(times) > 1:
        return ask("two_dates")
    if times and isinstance(times[0].value, str):
        return ask(times[0].value)
    if RE_RECURRENCE_KEYWORD.search(work):  # además de la serie, otra palabra de repetición
        return ask("unrecognized_recurrence")
    if RE_TIME_LEFTOVER.search(work):
        return ask("unrecognized_time")
    if parse_when(title, now, tz_name, default_morning, meridiem_ask_range).status != "none":
        return ask("two_dates")  # además de repetir, el texto trae otra fecha

    rrule = found[0][1]
    clock = times[0].value if times else default_morning
    assert isinstance(clock, time)
    moment = now()
    start = local_to_utc(datetime.combine(to_local(moment, tz_name).date(), clock), tz_name)
    first = next_occurrence(rrule, start, moment, tz_name)
    return RecurrenceResult(
        "ok",
        title,
        rrule,
        first,
        has_time=bool(times),
        meridiem_inferred=bool(times) and times[0].inferred,
    )


@dataclass(frozen=True)
class ScheduleResult:
    """Qué entendió el parser de un texto con fecha: `none`, un aviso `once`, una `series` o `ask`.

    Trae el resultado detallado del parser que contestó (`when` o `series`) para que el handler
    muestre la interpretación y las opciones antes de guardar.
    """

    kind: Literal["none", "once", "series", "ask"]
    title: str
    when: WhenResult | None = None
    series: RecurrenceResult | None = None
    reason: str | None = None


_parse_single = parse_when  # nombre aparte para poder comprobar el orden en las pruebas


def parse_schedule(
    text: str,
    now: Clock,
    tz_name: str,
    default_morning: time,
    meridiem_ask_range: tuple[int, int] = DEFAULT_MERIDIEM_ASK_RANGE,
) -> ScheduleResult:
    """Flujo del handler: PRIMERO la repetición, LUEGO la fecha suelta.

    Así "todos los lunes a las 7 pm" nunca se guarda como un aviso único, y una palabra de
    repetición que no se entiende ("cada mes") se pregunta en vez de tratarse como fecha.
    La fecha suelta solo se consulta si la repetición dijo `none`.
    """
    series = parse_recurrence(text, now, tz_name, default_morning, meridiem_ask_range)
    if series.status == "ok":
        return ScheduleResult("series", series.title, series=series)
    if series.status == "ask":
        return ScheduleResult("ask", series.title, series=series, reason=series.reason)
    when = _parse_single(text, now, tz_name, default_morning, meridiem_ask_range)
    if when.status == "ok":
        return ScheduleResult("once", when.title, when=when)
    if when.status == "ask":
        return ScheduleResult("ask", when.title, when=when, reason=when.reason)
    return ScheduleResult("none", when.title, when=when)
