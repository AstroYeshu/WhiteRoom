"""Barrido de reloj: cada hora de una semana, los días de cambio de horario y el 29/02.

Sin dependencias nuevas: un bucle sobre relojes falsos y una lista de frases. Invariantes:
  1. Nunca lanza una excepción, tampoco en las horas de cambio de horario (inexistente/repetida).
  2. Nunca devuelve una fecha en el pasado (resultado `ok` y candidatos de `ask` > reloj).
  3. Los candidatos son futuros, sin duplicados y en orden.
  4. Si la frase trae una hora escrita, aparece en el resultado (en alguna de sus lecturas am/pm).
     En los días de cambio de horario solo se exigen 1-3: esa deuda está anotada (ver
     `tests/test_dst_known_debt.py` y "Deuda conocida" en docs/PLAN_FASE1.md).
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from asistente.parsing.dates import parse_when
from asistente.parsing.recurrence import parse_schedule
from asistente.timeutil import local_to_utc, to_local

DEFAULT_MORNING = time(9, 0)
MEXICO, NEW_YORK, MADRID = "America/Mexico_City", "America/New_York", "Europe/Madrid"

# (frase, lecturas locales posibles de la hora escrita o None si no trae hora)
PHRASES: list[tuple[str, set[tuple[int, int]] | None]] = [
    ("mañana a las 8 am", {(8, 0)}),
    ("mañana a las 8 pm", {(20, 0)}),
    ("hoy a las 8 pm", {(20, 0)}),
    ("hoy a las 11 pm", {(23, 0)}),
    ("a las 8 pm", {(20, 0)}),
    ("a las 4", {(4, 0), (16, 0)}),
    ("a las 8", {(8, 0), (20, 0)}),
    ("a las 4 y media", {(4, 30), (16, 30)}),
    ("mañana a las 7 y 20", {(7, 20), (19, 20)}),
    ("mañana a las 3", {(3, 0), (15, 0)}),
    ("mañana a las 3 am", {(3, 0)}),
    ("mañana a las 12 am", {(0, 0)}),
    ("mañana a mediodía", {(12, 0)}),
    ("mañana a medianoche", {(0, 0)}),
    ("el domingo a las 5 pm", {(17, 0)}),
    ("el lunes 7:30 am", {(7, 30)}),
    ("pasado mañana a las 6 pm", {(18, 0)}),
    ("en 2 días a las 3 pm", {(15, 0)}),
    ("el 5 a las 10 am", {(10, 0)}),
    ("el 3 de octubre a las 2 pm", {(14, 0)}),
    ("el 29 de febrero a las 9 am", {(9, 0)}),
    ("a las 13:45", {(13, 45)}),
    ("a las 2:30 de la madrugada", {(2, 30)}),
    ("mañana", None),
    ("el domingo", None),
    ("el 5", None),
    ("el 29 de febrero", None),
    ("en 3 horas", None),
    ("en 45 minutos", None),
]
SERIES = [
    ("todos los lunes a las 7 pm", {(19, 0)}),
    ("cada día a las 8 pm", {(20, 0)}),
    ("diario a las 6 am", {(6, 0)}),
    ("de lunes a viernes a las 7:30 am", {(7, 30)}),
]

# Días en que cambia el horario (fecha local del cambio)
DST_DAYS = {
    NEW_YORK: [date(2026, 3, 8), date(2026, 11, 1), date(2027, 3, 14), date(2027, 11, 7)],
    MADRID: [date(2026, 3, 29), date(2026, 10, 25), date(2027, 3, 28)],
    MEXICO: [],
}


def _clocks(tz: str, first_day: date, days: int, minutes: tuple[int, ...] = (0, 30)):
    """Un reloj por cada hora REAL entre las 00:00 locales de `first_day` y `days` días después."""
    start = local_to_utc(datetime.combine(first_day, time(0, 0)), tz)
    for hour in range(days * 24):
        for minute in minutes:
            yield start + timedelta(hours=hour, minutes=minute)


WINDOWS: list[tuple[str, str, date, int]] = [
    ("semana-mexico", MEXICO, date(2026, 10, 3), 7),
    ("semana-nueva-york", NEW_YORK, date(2026, 10, 3), 7),
    ("semana-madrid", MADRID, date(2026, 10, 3), 7),
    ("bisiesto-mexico", MEXICO, date(2028, 2, 28), 3),
    ("bisiesto-nueva-york", NEW_YORK, date(2028, 2, 28), 3),
]
for _tz, _days in DST_DAYS.items():
    for _day in _days:
        WINDOWS.append((f"cambio-{_tz.split('/')[1]}-{_day}", _tz, _day - timedelta(days=1), 3))


def _local_text(moment: datetime, tz: str) -> str:
    return to_local(moment, tz).strftime("%Y-%m-%d %H:%M %Z")


def _violations(
    phrase: str, readings, moment: datetime, tz: str, dates: list[datetime], dst_day: bool
) -> list[str]:
    problems: list[str] = []
    for found in dates:
        if found <= moment:
            problems.append(f"en el pasado: {_local_text(found, tz)}")
        if readings is not None and not dst_day:
            local = to_local(found, tz)
            if (local.hour, local.minute) not in readings:
                problems.append(f"la hora escrita no aparece: {_local_text(found, tz)}")
    return problems


@pytest.mark.parametrize(("name", "tz", "first_day", "days"), WINDOWS, ids=[w[0] for w in WINDOWS])
def test_barrido_de_reloj(name, tz, first_day, days):
    zone = ZoneInfo(tz)
    dst_days = set(DST_DAYS[tz])
    failures: list[str] = []
    for moment in _clocks(tz, first_day, days):
        for phrase, readings in PHRASES:
            try:
                result = parse_when(phrase, lambda m=moment: m, tz, DEFAULT_MORNING)
            except Exception as error:
                failures.append(f"EXCEPCIÓN {phrase!r} @ {_local_text(moment, tz)}: {error!r}")
                continue
            candidates = list(result.candidates)
            if len(set(candidates)) != len(candidates) or candidates != sorted(candidates):
                failures.append(f"candidatos repetidos o desordenados {phrase!r} @ {moment}")
            found = ([result.when_utc] if result.when_utc else []) + candidates
            # Un día de cambio de horario: el resultado o el reloj caen en ese día local
            touched = {to_local(moment, tz).date(), *(to_local(f, tz).date() for f in found)}
            dst_day = bool(touched & dst_days)
            for problem in _violations(phrase, readings, moment, tz, found, dst_day):
                failures.append(f"{phrase!r} @ {_local_text(moment, tz)}: {problem}")
            if result.status == "ok" and readings is not None and not result.has_time:
                failures.append(f"{phrase!r} @ {_local_text(moment, tz)}: sin has_time")
        for phrase, readings in SERIES:
            try:
                scheduled = parse_schedule(phrase, lambda m=moment: m, tz, DEFAULT_MORNING)
            except Exception as error:
                failures.append(f"EXCEPCIÓN {phrase!r} @ {_local_text(moment, tz)}: {error!r}")
                continue
            if scheduled.series is not None and scheduled.series.first_at_utc is not None:
                first = scheduled.series.first_at_utc
                dst_day = bool({to_local(moment, tz).date(), to_local(first, tz).date()} & dst_days)
                for problem in _violations(phrase, readings, moment, tz, [first], dst_day):
                    failures.append(f"{phrase!r} @ {_local_text(moment, tz)}: {problem}")
    assert zone is not None
    assert failures == [], "\n" + "\n".join(failures[:25]) + f"\n({len(failures)} fallos en total)"


def test_el_barrido_cubre_lo_prometido():
    names = [w[0] for w in WINDOWS]
    assert sum(1 for n in names if n.startswith("semana")) == 3  # 168 h x 3 zonas
    assert sum(1 for n in names if n.startswith("cambio")) == 4 + 3  # cada cambio de horario
    assert sum(1 for n in names if n.startswith("bisiesto")) == 2  # 29/02/2028
    assert len(list(_clocks(MEXICO, date(2026, 10, 3), 7, (0,)))) == 168


def test_las_invariantes_del_barrido_detectan_un_resultado_malo():
    moment = local_to_utc(datetime(2026, 10, 3, 15, 30), MEXICO)
    past = moment - timedelta(hours=1)
    wrong_hour = local_to_utc(datetime(2026, 10, 4, 9, 0), MEXICO)
    assert _violations("x", {(8, 0)}, moment, MEXICO, [past], False)  # en el pasado
    assert _violations("x", {(8, 0)}, moment, MEXICO, [wrong_hour], False)  # hora que no es
    assert not _violations("x", {(9, 0)}, moment, MEXICO, [wrong_hour], False)
    assert not _violations("x", {(8, 0)}, moment, MEXICO, [wrong_hour], True)  # día de cambio


def test_el_barrido_ejercita_resultados_ok_y_preguntas():
    statuses: set[str] = set()
    for moment in _clocks(MEXICO, date(2026, 10, 3), 2, (0,)):
        for phrase, _ in PHRASES:
            statuses.add(parse_when(phrase, lambda m=moment: m, MEXICO, DEFAULT_MORNING).status)
    assert statuses == {"ok", "ask"}
