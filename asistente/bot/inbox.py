"""Bandeja de mensajes libres: guardar primero, preguntar después.

Un mensaje que no es un comando se guarda AL INSTANTE como tarea sin área (bandeja); nada se
pierde aunque el usuario no conteste. Luego se le pregunta qué es (tarea, recordatorio o nota),
en qué área va y, si es un recordatorio, cuándo (con las preguntas del parser como botones).
Convertir en recordatorio o nota cierra la tarea de bandeja con `close_as_converted`.

El texto del usuario NUNCA va al log: solo ids.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time

from asistente import formato as fmt
from asistente.bot.conversation import (
    STEP_AREA,
    STEP_AREA_DESC,
    STEP_DEADLINE,
    STEP_KIND,
    STEP_SERIES,
    STEP_WHEN,
    Conversation,
    Deadline,
    Flow,
    Pending,
)
from asistente.bot.ui import STALE_CHOICE_TEXT, show, shown
from asistente.channels.base import Channel, Choice, IncomingChoice
from asistente.choices import encode_choice_id
from asistente.core import areas, notes, reminders, tasks
from asistente.core.settings import get_meridiem_ask_range, get_time_setting
from asistente.parsing.dates import (
    WEEKDAY_NAMES_ES,
    fold,
    format_when,
    parse_when,
    strip_reminder_verb,
)
from asistente.parsing.recurrence import ScheduleResult, parse_schedule
from asistente.timeutil import Clock, local_to_utc, to_local

logger = logging.getLogger(__name__)

ACTION_FLOW = "in"  # in:FLUJO:ACCION[:ARGUMENTO]
ACTION_UNDO = "un"  # un:RECORDATORIO:TAREA
ACTION_CHANGE = "ch"  # ch:RECORDATORIO:TAREA

KIND_ACTION = "k"  # acción del botón de tipo; su argumento es uno de los KIND_*
KIND_TASK, KIND_REMINDER, KIND_NOTE = "t", "r", "n"
KIND_LABELS = {KIND_TASK: "Tarea", KIND_REMINDER: "Recordatorio", KIND_NOTE: "Nota"}
REMINDER_VERBS = frozenset({"recordar", "recordarme", "recuerdame", "recuerdenme"})
EVENING = time(18, 0)  # la opción "Hoy 18:00" de la pregunta ¿cuándo?

ABANDONED_TEXT = "Dejé sin terminar lo anterior; sigue en tu bandeja como tarea."
ABANDONED_AREA_TEXT = "Dejé sin terminar la creación del área."
CANCELLED_TEXT = "Cancelado. «{text}» sigue en tu bandeja como tarea."
CANCELLED_AREA_TEXT = "Cancelado. No se creó el área."
AREA_DESCRIPTION_PROMPT = "¿Qué cubre «{name}»? Escribe una descripción corta u omítela."
WHEN_PROMPT = (
    '¿Cuándo? Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".'
)
WRITE_WHEN_PROMPT = "Escribe la fecha y la hora, por ejemplo «mañana 8 pm»."
PAST_PROMPT = f"Esa hora ya pasó. {WHEN_PROMPT}"
NOT_UNDOABLE_TEXT = "Ya no se puede deshacer ni cambiar: ese recordatorio ya no está pendiente."

CANCEL = ("x", None, "Cancelar")
AS_TASK = ("t", None, "Mejor como tarea")
Button = tuple[str, object | None, str]  # (acción, argumento, texto del botón)

# Preguntas del parser (docs/PLAN_FASE1.md). Con candidatos, cada uno es un botón.
QUESTION_TEXT = {
    "time_or_verse": "¿Eso es una hora o una cita bíblica?",
    "name_or_day": "¿«Domingo» es una persona o el día de la semana?",
    "dotted_time": "¿Es una hora? Escríbela con dos puntos (por ejemplo 7:30).",
    "number_after_day": "¿Ese número es la hora o forma parte del texto? Escribe la hora completa.",
    "unsupported_date": "No entiendo esa fecha. ¿Qué día quieres?",
    "unrecognized_recurrence": (
        "Esa repetición no está entre las que sé hacer (todos los días, cada lunes, "
        "de lunes a viernes)."
    ),
    "ambiguous_time": "¿Medianoche de qué día?",
    "today_or_tomorrow": "Ya pasó la medianoche: ¿«mañana» es hoy o mañana?",
    "same_weekday": "Hoy es ese día: ¿hoy o en 7 días?",
}
GENERIC_QUESTION_TEXT = "No pude entender la fecha o la hora; escríbela de otra forma."
# Respuestas del parser que no son sobre la fecha sino sobre el texto: no cuentan como respuesta.
NOT_A_DATE_ANSWER = frozenset({"name_or_day", "time_or_verse"})
NO_DATE_BUTTONS = {
    "time_or_verse": "Es una cita",
    "name_or_day": "Es un nombre",
    "unrecognized_recurrence": "Solo una vez…",
}


@dataclass(frozen=True)
class Ctx:
    """Todo lo que necesita un paso de la conversación."""

    channel: Channel
    conn: sqlite3.Connection
    now: Clock
    tz_name: str
    conversation: Conversation
    user_ref: str


# --- Utilidades ------------------------------------------------------------------------------


def starts_with_reminder_verb(text: str) -> bool:
    words = fold(text).split()
    return bool(words) and words[0].strip(",.:;!¡¿?") in REMINDER_VERBS


def describe_rrule(rrule: str) -> str:
    """La repetición en palabras, para mostrarla antes de guardar."""
    if rrule == "FREQ=DAILY":
        return "Todos los días"
    if rrule == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR":
        return "De lunes a viernes"
    days = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    for code, name in zip(days, WEEKDAY_NAMES_ES, strict=True):
        if rrule == f"FREQ=WEEKLY;BYDAY={code}":
            return f"Cada {name}"
    return "Se repite"


def _clock_text(moment: datetime, ctx: Ctx) -> str:
    """ "8:00 pm" (la hora de format_when, sin el día)."""
    return format_when(moment, ctx.tz_name, ctx.now).rpartition(", ")[2]


def _area_name(ctx: Ctx, area_id: int | None) -> str | None:
    area = areas.get_area(ctx.conn, area_id) if area_id is not None else None
    return area.name if area is not None else None


async def _say(ctx: Ctx, choice: IncomingChoice | None, text: str) -> None:
    """Edita el mensaje del botón; si no hubo botón (el usuario escribió), manda uno nuevo."""
    if choice is None:
        await ctx.channel.send_text(ctx.user_ref, text)
    else:
        await show(ctx.channel, choice, text)


async def _ack(ctx: Ctx, choice: IncomingChoice | None, text: str) -> None:
    """Deja constancia de la respuesta en el mensaje de la pregunta (solo si fue un botón)."""
    if choice is not None:
        await show(ctx.channel, choice, text)


async def _send_question(ctx: Ctx, flow: Flow, step: str, text: str, buttons: list[Button]) -> None:
    """Hace una pregunta NUEVA. Renueva el id del flujo: los botones de la pregunta anterior
    (que puede seguir en pantalla) quedan viejos y ya no hacen nada."""
    flow.step = step
    ctx.conversation.renew(flow, ctx.now)
    choices = [
        Choice(
            encode_choice_id(ACTION_FLOW, flow.id, action, *([arg] if arg is not None else [])),
            label,
        )
        for action, arg, label in buttons
    ]
    await ctx.channel.send_choices(ctx.user_ref, text, choices)


def _parse(ctx: Ctx, text: str) -> ScheduleResult:
    return parse_schedule(
        text,
        ctx.now,
        ctx.tz_name,
        get_time_setting(ctx.conn, "default_morning_time"),
        get_meridiem_ask_range(ctx.conn),
    )


def _is_date_answer(result: ScheduleResult) -> bool:
    """¿El parser entendió el texto como una fecha (aunque tenga que preguntar un detalle)?"""
    if result.kind in ("once", "series"):
        return True
    return result.kind == "ask" and result.reason not in NOT_A_DATE_ANSWER


# --- Mensaje libre ---------------------------------------------------------------------------


async def capture(ctx: Ctx, text: str) -> None:
    """Un mensaje libre: descripción del área, respuesta a ¿cuándo? o una captura nueva."""
    text = text.strip()
    if not text:
        return
    flow = ctx.conversation.current(ctx.now)
    if flow is not None and flow.step == STEP_AREA_DESC:  # todo lo que no es comando
        await _finish_area(ctx, flow, text, None)
        return
    if flow is not None and flow.step == STEP_WHEN:
        result = _parse(ctx, text)
        if _is_date_answer(result):
            await _apply_schedule(ctx, flow, result, None)
            return
    await _start_capture(ctx, text, None, False)


async def capture_as(
    ctx: Ctx, text: str, kind: str, preview: bool = False, ask_deadline: bool = False
) -> None:
    """/tarea, /nota, /recordar: el tipo ya está dicho; solo falta el área (y la fecha).

    `ask_deadline` (solo /tarea): si el texto trae una fecha clara, después del área se pregunta
    si es la fecha límite."""
    text = text.strip()
    if text:
        await _start_capture(ctx, text, kind, preview, ask_deadline)


async def _drop_current_flow(ctx: Ctx) -> None:
    """Suelta lo que hubiera a medias, avisando (la tarea ya está guardada en la bandeja)."""
    flow = ctx.conversation.current(ctx.now)
    if flow is not None:
        ctx.conversation.clear()
        notice = ABANDONED_AREA_TEXT if flow.step == STEP_AREA_DESC else ABANDONED_TEXT
        await ctx.channel.send_text(ctx.user_ref, notice)


async def _start_capture(
    ctx: Ctx, text: str, kind: str | None, preview: bool, ask_deadline: bool = False
) -> None:
    """Guarda el texto en la bandeja y pregunta lo que falte. `kind` None = preguntar el tipo."""
    await _drop_current_flow(ctx)
    task = tasks.create_task(ctx.conn, text, ctx.now, source_text=text)
    logger.info("Bandeja: tarea guardada id=%s", task.id)
    flow = ctx.conversation.start(task.id, text, ctx.now)
    header = f"Guardado en tu bandeja: «{shown(text)}»\n"
    if kind is None and starts_with_reminder_verb(text):  # ya dijo qué es: no se pregunta
        kind = KIND_REMINDER
    if kind is not None:
        flow.kind, flow.preview = kind, preview
        if ask_deadline:
            flow.deadline = _detect_deadline(ctx, text)
        await _ask_area(ctx, flow, None, header)
        return
    buttons: list[Button] = [(KIND_ACTION, kind, label) for kind, label in KIND_LABELS.items()]
    await _send_question(ctx, flow, STEP_KIND, header + "¿Qué es?", [*buttons, CANCEL])


# --- Área ------------------------------------------------------------------------------------


async def _ask_area(ctx: Ctx, flow: Flow, choice: IncomingChoice | None, header: str = "") -> None:
    available = areas.list_areas(ctx.conn)
    if not available:  # sin áreas que ofrecer no hay nada que preguntar
        flow.area_id = None
        await _after_area(ctx, flow, choice, KIND_LABELS[flow.kind or KIND_TASK])
        return
    buttons: list[Button] = [("a", area.id, fmt.label(area.name)) for area in available]
    buttons += [("a", 0, "Sin área"), CANCEL]
    await _send_question(ctx, flow, STEP_AREA, header + "¿En qué área va?", buttons)


async def _after_area(ctx: Ctx, flow: Flow, choice: IncomingChoice | None, ack: str) -> None:
    """Ya se sabe tipo y área: se termina (tarea, nota) o se sigue con la fecha (recordatorio)."""
    area = _area_name(ctx, flow.area_id)
    suffix = f" en {area}" if area else ""
    if flow.kind == KIND_TASK and flow.deadline is not None:
        await _ask_deadline(ctx, flow, choice, ack)
    elif flow.kind == KIND_TASK:
        tasks.set_area(ctx.conn, flow.task_id, flow.area_id, ctx.now)
        ctx.conversation.clear()
        await _say(ctx, choice, f"Tarea guardada{suffix}: «{shown(flow.text)}»")
    elif flow.kind == KIND_NOTE:
        notes.create_note(ctx.conn, flow.text, ctx.now, area_id=flow.area_id)
        tasks.close_as_converted(ctx.conn, flow.task_id, "converted_to_note", ctx.now)
        ctx.conversation.clear()
        await _say(ctx, choice, f"Nota guardada{suffix}: «{shown(flow.text)}»")
    else:
        await _ack(ctx, choice, ack)
        result = _parse(ctx, flow.text)
        flow.title = strip_reminder_verb(result.title).strip() or flow.text
        await _apply_schedule(ctx, flow, result, None)


# --- Fecha límite de una tarea (/tarea) ------------------------------------------------------


def _detect_deadline(ctx: Ctx, text: str) -> Deadline | None:
    """Una fecha CLARA en el texto (`ok`); si el parser duda o no hay fecha, no se pregunta nada."""
    result = parse_when(
        text,
        ctx.now,
        ctx.tz_name,
        get_time_setting(ctx.conn, "default_morning_time"),
        get_meridiem_ask_range(ctx.conn),
    )
    if result.status != "ok" or result.when_utc is None:
        return None
    title = strip_reminder_verb(result.title).strip() or text
    return Deadline(result.when_utc, result.has_time, title)


async def _ask_deadline(ctx: Ctx, flow: Flow, choice: IncomingChoice | None, ack: str) -> None:
    deadline = flow.deadline
    assert deadline is not None
    await _ack(ctx, choice, ack)
    when = format_when(deadline.when_utc, ctx.tz_name, ctx.now)
    default = "" if deadline.has_time else " (hora por defecto)"
    text = f"¿Es la fecha límite de «{shown(deadline.title)}»?\nFecha: {when}{default}"
    buttons: list[Button] = [("ly", None, "Sí"), ("ln", None, "No"), CANCEL]
    await _send_question(ctx, flow, STEP_DEADLINE, text, buttons)


async def _finish_task(ctx: Ctx, flow: Flow, choice: IncomingChoice, with_deadline: bool) -> None:
    tasks.set_area(ctx.conn, flow.task_id, flow.area_id, ctx.now)
    area = _area_name(ctx, flow.area_id)
    suffix = f" en {area}" if area else ""
    deadline = flow.deadline
    ctx.conversation.clear()
    if with_deadline and deadline is not None:
        tasks.set_title(ctx.conn, flow.task_id, deadline.title, ctx.now)
        tasks.set_due(ctx.conn, flow.task_id, deadline.when_utc, ctx.now)
        when = format_when(deadline.when_utc, ctx.tz_name, ctx.now)
        text = f"Tarea guardada{suffix}: «{shown(deadline.title)}» (vence: {when})"
    else:
        text = f"Tarea guardada{suffix}: «{shown(flow.text)}»"
    await show(ctx.channel, choice, text)


async def _on_deadline_yes(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _finish_task(ctx, flow, choice, True)
    return True


async def _on_deadline_no(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _finish_task(ctx, flow, choice, False)
    return True


# --- Fecha -----------------------------------------------------------------------------------


def _quick_targets(ctx: Ctx) -> dict[str, tuple[datetime, str]]:
    """Las opciones rápidas de ¿cuándo?: acción -> (momento UTC, texto del botón)."""
    moment = ctx.now()
    targets: dict[str, tuple[datetime, str]] = {}
    evening = local_to_utc(
        datetime.combine(to_local(moment, ctx.tz_name).date(), EVENING), ctx.tz_name
    )
    if evening > moment:
        targets["h"] = (evening, f"Hoy {EVENING.hour}:{EVENING.minute:02d}")
    tomorrow = reminders.tomorrow_target(ctx.conn, moment, ctx.tz_name)
    local = to_local(tomorrow, ctx.tz_name)
    day = "Hoy" if local.date() == to_local(moment, ctx.tz_name).date() else "Mañana"
    targets["m"] = (tomorrow, f"{day} {local.hour}:{local.minute:02d}")
    return targets


async def _ask_when(ctx: Ctx, flow: Flow, text: str, extra: list[Button] | None = None) -> None:
    flow.candidates = ()
    quick: list[Button] = [(key, None, label) for key, (_, label) in _quick_targets(ctx).items()]
    await _send_question(ctx, flow, STEP_WHEN, text, [*(extra or []), *quick, AS_TASK, CANCEL])


def _question_text(ctx: Ctx, reason: str | None, candidates: tuple[datetime, ...]) -> str:
    if reason == "ambiguous_meridiem" and candidates:
        if len(candidates) == 1:
            return f"¿A las {_clock_text(candidates[0], ctx)}?"
        hour = _clock_text(candidates[0], ctx).split(":")[0]
        return f"¿A las {hour} am o pm?"
    if reason == "past":
        if candidates:
            when = format_when(candidates[0], ctx.tz_name, ctx.now)
            return f"Esa fecha ya pasó. ¿La dejo para {when}?"
        return "Esa fecha ya pasó. Escribe otra."
    return QUESTION_TEXT.get(reason or "", GENERIC_QUESTION_TEXT)


async def _ask_when_question(ctx: Ctx, flow: Flow, result: ScheduleResult) -> None:
    """La pregunta del parser como botones: un botón por candidato más escribir otra/cancelar."""
    candidates = result.when.candidates if result.when is not None else ()
    text = _question_text(ctx, result.reason, candidates)
    buttons: list[Button] = [
        ("w", index, fmt.fecha_corta(moment, ctx.tz_name, ctx.now))
        for index, moment in enumerate(candidates)
    ]
    if result.reason in NO_DATE_BUTTONS:
        buttons.append(("n", None, NO_DATE_BUTTONS[result.reason]))
    if result.reason == "unsupported_date" and not candidates:
        buttons += [(key, None, label) for key, (_, label) in _quick_targets(ctx).items()]
    buttons += [("o", None, "Escribir otra fecha"), CANCEL]
    await _send_question(ctx, flow, STEP_WHEN, text, buttons)
    flow.candidates = candidates  # después de renovar el id; los botones llevan solo el índice


async def _apply_schedule(
    ctx: Ctx, flow: Flow, result: ScheduleResult, choice: IncomingChoice | None
) -> None:
    """Qué hacer con lo que entendió el parser: guardar, previsualizar, preguntar o pedir fecha."""
    if result.kind == "once" and result.when is not None and result.when.when_utc is not None:
        await _propose(ctx, flow, choice, result.when.when_utc, None, result.when.has_time)
    elif result.kind == "series" and result.series is not None:
        series = result.series
        assert series.first_at_utc is not None and series.rrule is not None
        await _propose(ctx, flow, choice, series.first_at_utc, series.rrule, series.has_time)
    elif result.kind == "ask":
        await _ask_when_question(ctx, flow, result)
    else:
        await _ask_when(ctx, flow, WHEN_PROMPT)


async def _propose(
    ctx: Ctx,
    flow: Flow,
    choice: IncomingChoice | None,
    when_utc: datetime,
    rrule: str | None,
    has_time: bool,
) -> None:
    """Una fecha ya resuelta: se guarda y se confirma (con Cambiar/Deshacer), salvo una repetición
    o un /recordar, que muestran primero la interpretación y esperan «Guardar»."""
    if rrule is None and not flow.preview:
        await _create(ctx, flow, choice, when_utc, rrule, has_time)
        return
    flow.pending = Pending(when_utc, rrule, has_time)
    when = format_when(when_utc, ctx.tz_name, ctx.now)
    await _ack(ctx, choice, f"Elegido: {when}")
    if rrule is not None:
        text = (
            f"Repetición: {describe_rrule(rrule)}: «{shown(flow.title)}»\n"
            f"Próxima: {when}\n¿La guardo?"
        )
    else:
        lines = [f"Recordatorio: «{shown(flow.title)}»"]
        lines.append(f"Cuándo: {when}{'' if has_time else ' (hora por defecto)'}")
        area = _area_name(ctx, flow.area_id)
        if area:
            lines.append(f"Área: {area}")
        text = "\n".join([*lines, "¿Lo guardo?"])
    await _send_question(ctx, flow, STEP_SERIES, text, [("s", None, "Guardar"), CANCEL])


async def _create(
    ctx: Ctx,
    flow: Flow,
    choice: IncomingChoice | None,
    when_utc: datetime,
    rrule: str | None,
    has_time: bool,
) -> None:
    """Crea el recordatorio (cierra la tarea de bandeja en la misma transacción) y confirma."""
    try:
        reminder = tasks.convert_to_reminder(
            ctx.conn, flow.task_id, flow.title, when_utc, ctx.now, area_id=flow.area_id, rrule=rrule
        )
    except reminders.PastReminderError:  # la opción tardó tanto que ya pasó: jamás en el pasado
        await _ack(ctx, choice, "Esa hora ya pasó.")
        await _ask_when(ctx, flow, PAST_PROMPT)
        return
    if reminder is None:  # la tarea ya no está abierta: no hay nada que convertir
        ctx.conversation.clear()
        await _say(ctx, choice, STALE_CHOICE_TEXT)
        return
    ctx.conversation.clear()
    logger.info("Bandeja: tarea %s convertida en el recordatorio %s", flow.task_id, reminder.id)
    when = format_when(when_utc, ctx.tz_name, ctx.now)
    await _ack(ctx, choice, f"Listo: {when}")
    lines = [f"Listo: «{shown(reminder.text)}»"]
    if rrule is not None:
        lines.append(f"Repetición: {describe_rrule(rrule)}")
    lines.append(
        f"{'Próxima' if rrule else 'Cuándo'}: {when}{'' if has_time else ' (hora por defecto)'}"
    )
    area = _area_name(ctx, reminder.area_id)
    if area:
        lines.append(f"Área: {area}")
    ids = (reminder.id, flow.task_id)
    await ctx.channel.send_choices(
        ctx.user_ref,
        "\n".join(lines),
        [
            Choice(encode_choice_id(ACTION_CHANGE, *ids), "Cambiar"),
            Choice(encode_choice_id(ACTION_UNDO, *ids), "Deshacer"),
        ],
    )


# --- Área nueva (/nuevaarea) -------------------------------------------------------------------


async def start_new_area(ctx: Ctx, name: str) -> None:
    """El nombre ya está validado: se pregunta la descripción (se puede omitir)."""
    await _drop_current_flow(ctx)
    flow = ctx.conversation.start(0, name, ctx.now, STEP_AREA_DESC)
    text = AREA_DESCRIPTION_PROMPT.format(name=shown(name))
    await _send_question(ctx, flow, STEP_AREA_DESC, text, [("d", None, "Omitir"), CANCEL])


async def _finish_area(
    ctx: Ctx, flow: Flow, description: str, choice: IncomingChoice | None
) -> None:
    ctx.conversation.clear()
    try:
        area = areas.create_area(ctx.conn, flow.text, description, ctx.now)
    except areas.AreaError as error:  # p. ej. alguien creó el mismo nombre mientras tanto
        await _say(ctx, choice, str(error))
        return
    logger.info("Área creada id=%s", area.id)
    note = "" if area.description else " (sin descripción)"
    await _say(ctx, choice, f"Área creada: {area.name}{note}")


# --- Botones del flujo -----------------------------------------------------------------------


async def _on_kind(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if len(args) != 1 or args[0] not in KIND_LABELS:
        return False
    flow.kind = args[0]
    await _ack(ctx, choice, KIND_LABELS[args[0]])
    await _ask_area(ctx, flow, choice)
    return True


async def _on_area(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if len(args) != 1 or not _is_id(args[0]):
        return False
    area_id = int(args[0])
    area = areas.get_area(ctx.conn, area_id) if area_id else None
    if area_id and (area is None or area.archived):
        return False
    flow.area_id = area_id or None
    await _after_area(ctx, flow, choice, f"Área: {area.name}" if area else "Área: ninguna")
    return True


async def _on_candidate(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if len(args) != 1 or not _is_id(args[0]) or int(args[0]) >= len(flow.candidates):
        return False
    await _propose(ctx, flow, choice, flow.candidates[int(args[0])], None, True)
    return True


async def _on_quick(
    ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str], key: str
) -> bool:
    if args:
        return False
    target = _quick_targets(ctx).get(key)
    if target is None:  # "Hoy 18:00" que se pulsó cuando ya había pasado
        await _ack(ctx, choice, "Esa hora ya pasó.")
        await _ask_when(ctx, flow, PAST_PROMPT)
        return True
    await _propose(ctx, flow, choice, target[0], None, True)
    return True


async def _on_write_other(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _ack(ctx, choice, "Otra fecha")
    await _ask_when(ctx, flow, WRITE_WHEN_PROMPT)
    return True


async def _on_no_date(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _ack(ctx, choice, "Sin fecha en el texto")
    flow.title = flow.text
    await _ask_when(ctx, flow, WHEN_PROMPT)
    return True


async def _on_save(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    pending = flow.pending
    if args or pending is None:
        return False
    await _create(ctx, flow, choice, pending.when_utc, pending.rrule, pending.has_time)
    return True


async def _on_skip_description(
    ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]
) -> bool:
    if args:
        return False
    await _finish_area(ctx, flow, "", choice)
    return True


async def _on_better_as_task(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    """«Mejor como tarea»: queda como tarea (con el área elegida) y sin recordatorio."""
    if args:
        return False
    tasks.set_area(ctx.conn, flow.task_id, flow.area_id, ctx.now)
    ctx.conversation.clear()
    area = _area_name(ctx, flow.area_id)
    suffix = f" en {area}" if area else ""
    await show(ctx.channel, choice, f"Tarea guardada{suffix}: «{shown(flow.text)}»")
    return True


async def _on_cancel(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    ctx.conversation.clear()
    text = CANCELLED_AREA_TEXT if flow.step == STEP_AREA_DESC else CANCELLED_TEXT
    await show(ctx.channel, choice, text.format(text=shown(flow.text)))
    return True


def _is_id(part: str) -> bool:
    return part.isascii() and part.isdigit()


# acción -> (paso en el que vale, manejador). `None` = vale en cualquier paso.
_FLOW_ACTIONS = {
    KIND_ACTION: (STEP_KIND, _on_kind),
    "a": (STEP_AREA, _on_area),
    "w": (STEP_WHEN, _on_candidate),
    "o": (STEP_WHEN, _on_write_other),
    "n": (STEP_WHEN, _on_no_date),
    "t": (STEP_WHEN, _on_better_as_task),
    "s": (STEP_SERIES, _on_save),
    "d": (STEP_AREA_DESC, _on_skip_description),
    "ly": (STEP_DEADLINE, _on_deadline_yes),
    "ln": (STEP_DEADLINE, _on_deadline_no),
    "x": (None, _on_cancel),
}


async def handle_flow_choice(ctx: Ctx, choice: IncomingChoice, parts: list[str]) -> None:
    """`in:FLUJO:ACCION[:ARG]`. Mal formado, de otro flujo o de otro paso = botón viejo."""
    handled = False
    if len(parts) >= 2 and _is_id(parts[0]):
        flow = ctx.conversation.get(int(parts[0]), ctx.now)
        action, args = parts[1], parts[2:]
        if flow is not None:
            if action in ("h", "m") and flow.step == STEP_WHEN:
                handled = await _on_quick(ctx, flow, choice, args, action)
            elif action in _FLOW_ACTIONS:
                step, handler = _FLOW_ACTIONS[action]
                if step is None or flow.step == step:
                    handled = await handler(ctx, flow, choice, args)
    if not handled:
        await show(ctx.channel, choice, STALE_CHOICE_TEXT)


# --- Deshacer y Cambiar ----------------------------------------------------------------------


async def handle_conversion_choice(
    ctx: Ctx, choice: IncomingChoice, action: str, parts: list[str]
) -> None:
    """`un:RECORDATORIO:TAREA` / `ch:RECORDATORIO:TAREA`. Viven en la base, no en la memoria."""
    if len(parts) != 2 or not all(_is_id(part) for part in parts):
        await show(ctx.channel, choice, STALE_CHOICE_TEXT)
        return
    reminder_id, task_id = int(parts[0]), int(parts[1])
    reminder = reminders.get_reminder(ctx.conn, reminder_id)
    task = tasks.get_task(ctx.conn, task_id)
    if reminder is None or task is None:
        await show(ctx.channel, choice, STALE_CHOICE_TEXT)
        return
    if not tasks.undo_reminder_conversion(ctx.conn, task_id, reminder_id, ctx.now):
        await show(ctx.channel, choice, NOT_UNDOABLE_TEXT)
        return
    logger.info("Bandeja: recordatorio %s deshecho (tarea %s)", reminder_id, task_id)
    if action == ACTION_UNDO:
        await show(
            ctx.channel,
            choice,
            f"Deshecho. «{shown(reminder.text)}» vuelve a tu bandeja como tarea.",
        )
        return
    await show(ctx.channel, choice, f"Cambiando «{shown(reminder.text)}»")
    flow = ctx.conversation.start(task_id, task.source_text or task.title, ctx.now, STEP_WHEN)
    flow.kind, flow.area_id, flow.title = KIND_REMINDER, reminder.area_id, reminder.text
    await _ask_when(ctx, flow, WHEN_PROMPT)
