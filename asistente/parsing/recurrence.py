"""Recordatorios repetidos: lista CERRADA de expresiones -> regla `rrule` (RFC 5545).

Se entiende solo:
    "todos los días [hora]"
    "cada <día de la semana> [hora]"
    "de lunes a viernes [hora]"
Cualquier otra cosa no se interpreta (el handler pregunta). La hora usa las mismas reglas
que `parsing/dates.py`. `next_occurrence` es la función que también usa el motor de
recordatorios: calcula desde la hora PROGRAMADA (no desde `now`) y respeta el horario de verano.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Literal

from dateutil.rrule import rrulestr

from asistente.parsing.dates import (
    DEFAULT_MERIDIEM_ASK_RANGE,
    RE_TIME_LEFTOVER,
    WEEKDAYS,
    clean_title,
    fold,
    parse_when,
    scan_times,
    strip_reminder_verb,
)
from asistente.timeutil import Clock, local_to_utc, to_local

_RRULE_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")  # mismo orden que WEEKDAYS
_RE_DAILY = re.compile(r"\btodos\s+los\s+dias\b")
_RE_EVERY_WEEKDAY = re.compile(r"\bcada\s+(?P<wd>" + "|".join(WEEKDAYS) + r")\b")
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
    folded = fold(text)
    found: list[tuple[re.Match[str], str]] = []
    for match in _RE_DAILY.finditer(folded):
        found.append((match, "FREQ=DAILY"))
    for match in _RE_WORKDAYS.finditer(folded):
        found.append((match, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"))
    for match in _RE_EVERY_WEEKDAY.finditer(folded):
        day = _RRULE_DAYS[WEEKDAYS.index(match["wd"])]
        found.append((match, f"FREQ=WEEKLY;BYDAY={day}"))
    if not found:
        return RecurrenceResult("none", clean_title(text, []))

    work = folded
    for match, _ in found:
        work = work[: match.start()] + " " * (match.end() - match.start()) + work[match.end() :]
    strong, weak, work = scan_times(work, meridiem_ask_range)
    times = strong + weak  # la repetición hace de "día": una hora suelta 8:30 sí cuenta
    for hit in weak:
        work = work[: hit.start] + " " * (hit.end - hit.start) + work[hit.end :]
    spans = [(m.start(), m.end()) for m, _ in found] + [(h.start, h.end) for h in times]
    title = strip_reminder_verb(clean_title(text, spans))

    def ask(reason: str) -> RecurrenceResult:
        return RecurrenceResult("ask", title, reason=reason)

    if len(found) > 1 or len(times) > 1:
        return ask("two_dates")
    if times and isinstance(times[0].value, str):
        return ask(times[0].value)
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
