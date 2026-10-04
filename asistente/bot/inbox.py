"""Bandeja de mensajes libres: guardar primero, preguntar después, todo en UNA tarjeta.

Un mensaje que no es un comando se guarda AL INSTANTE como tarea sin área (bandeja); nada se
pierde aunque el usuario no conteste. El bot abre UN mensaje (la "tarjeta") con la primera
pregunta y lo va EDITANDO en su lugar: tipo, área, fecha y, al final, la confirmación. Si el canal
no puede editar (consola, o Telegram falla), se manda un mensaje nuevo y se sigue en ese.
Convertir en recordatorio o nota cierra la tarea de bandeja con `close_as_converted`.

Los textos y la distribución de botones salen de `formato.py`. El texto del usuario NUNCA va al
log: solo ids.
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
from asistente.core.runtime import RuntimeStatus
from asistente.core.settings import get_meridiem_ask_range, get_time_setting
from asistente.parsing.dates import WEEKDAY_NAMES_ES, fold, parse_when, strip_reminder_verb
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
EVENING = time(18, 0)  # la opción "Hoy 6:00 pm" de la pregunta ¿cuándo?

CANCEL = ("x", None, fmt.BTN_CANCEL)
AS_TASK = ("t", None, fmt.BTN_AS_TASK)
Button = tuple[str, object | None, str]  # (acción, argumento, texto del botón)

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
    runtime: RuntimeStatus | None = None  # lo que solo sabe el proceso en marcha (/estado)


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


def _area_name(ctx: Ctx, area_id: int | None) -> str | None:
    area = areas.get_area(ctx.conn, area_id) if area_id is not None else None
    return area.name if area is not None else None


def _content(flow: Flow) -> str:
    """Lo que escribió el usuario (o el título ya limpio), para repetirlo en la tarjeta."""
    return shown(flow.title or flow.text)


def _details(ctx: Ctx, flow: Flow) -> list[fmt.Html]:
    """Los datos ya elegidos, con etiqueta: Tipo y Área."""
    lines: list[fmt.Html] = []
    if flow.kind:
        lines.append(fmt.detail("Tipo", KIND_LABELS[flow.kind]))
    area = _area_name(ctx, flow.area_id)
    if area:
        lines.append(fmt.detail("Área", area))
    return lines


def _area_line(ctx: Ctx, area_id: int | None) -> list[fmt.Html]:
    area = _area_name(ctx, area_id)
    return [fmt.detail("Área", area)] if area else []


def _when_line(ctx: Ctx, when_utc: datetime, has_time: bool, label: str = "Cuándo") -> fmt.Html:
    when = fmt.fecha_larga(when_utc, ctx.tz_name, ctx.now)
    return fmt.detail(label, when + ("" if has_time else " (hora por defecto)"))


async def _present(
    ctx: Ctx,
    flow: Flow,
    text: str,
    choices: list[Choice] | None = None,
    layout: tuple[int, ...] | None = None,
) -> None:
    """Muestra `text` en la tarjeta del flujo: la edita; si no hay tarjeta o no se pudo editar,
    manda un mensaje nuevo y esa pasa a ser la tarjeta."""
    ref = flow.message_ref
    if ref is not None and await ctx.channel.edit_text(ctx.user_ref, ref, text, choices, layout):
        return
    if choices:
        flow.message_ref = await ctx.channel.send_choices(
            ctx.user_ref, text, choices, layout=layout
        )
    else:
        flow.message_ref = await ctx.channel.send_text(ctx.user_ref, text)


async def _ask(
    ctx: Ctx, flow: Flow, step: str, text: str, buttons: list[Button], tail: int = 2
) -> None:
    """Hace una pregunta en la tarjeta. Renueva el id del flujo: los botones de la pregunta
    anterior (que pueden seguir en pantalla) quedan viejos y ya no hacen nada."""
    flow.step = step
    ctx.conversation.renew(flow, ctx.now)
    choices = [
        Choice(
            encode_choice_id(ACTION_FLOW, flow.id, action, *([arg] if arg is not None else [])),
            label,
        )
        for action, arg, label in buttons
    ]
    await _present(ctx, flow, text, choices, fmt.tail_layout(len(choices), tail))


async def _finish(
    ctx: Ctx,
    flow: Flow,
    text: str,
    choices: list[Choice] | None = None,
    layout: tuple[int, ...] | None = None,
) -> None:
    """El flujo terminó: la tarjeta queda como constancia (con sus botones finales, si hay)."""
    ctx.conversation.clear()
    await _present(ctx, flow, text, choices, layout)


async def _stale(ctx: Ctx, choice: IncomingChoice) -> str | None:
    """Botón viejo. Devuelve el aviso breve (o None).

    - El mismo botón que se acaba de atender (doble pulsación): no pasa nada.
    - Un botón de un paso viejo sobre la tarjeta VIVA: aviso breve, sin crear ni editar mensajes
      (la pregunta vigente no se toca).
    - Un botón en una tarjeta muerta: esa tarjeta se marca como no disponible.
    """
    if choice.choice_id == ctx.conversation.last_press_id:
        return None
    flow = ctx.conversation.current(ctx.now)
    if flow is not None and flow.message_ref is not None and flow.message_ref == choice.message_ref:
        return fmt.TOAST_STALE
    await show(ctx.channel, choice, STALE_CHOICE_TEXT)
    return None


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
        await _finish_area(ctx, flow, text)
        return
    if flow is not None and flow.step == STEP_WHEN:
        result = _parse(ctx, text)
        if _is_date_answer(result):
            await _apply_schedule(ctx, flow, result)
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
    """Suelta lo que hubiera a medias: la tarjeta vieja se EDITA ("Sin terminar") y la tarea ya
    guardada sigue en la bandeja. Solo si no se puede editar se manda un aviso aparte."""
    flow = ctx.conversation.current(ctx.now)
    if flow is None:
        return
    ctx.conversation.clear()
    note = fmt.NOTE_NO_AREA if flow.step == STEP_AREA_DESC else fmt.NOTE_IN_INBOX
    text = fmt.card(fmt.ABANDONED, shown(flow.text), note=note)
    ref = flow.message_ref
    if ref is None or not await ctx.channel.edit_text(ctx.user_ref, ref, text):
        await ctx.channel.send_text(ctx.user_ref, text)


async def _start_capture(
    ctx: Ctx, text: str, kind: str | None, preview: bool, ask_deadline: bool = False
) -> None:
    """Guarda el texto en la bandeja y abre la tarjeta. `kind` None = preguntar el tipo."""
    await _drop_current_flow(ctx)
    task = tasks.create_task(ctx.conn, text, ctx.now, source_text=text)
    logger.info("Bandeja: tarea guardada id=%s", task.id)
    flow = ctx.conversation.start(task.id, text, ctx.now)
    if kind is None and starts_with_reminder_verb(text):  # ya dijo qué es: no se pregunta
        kind = KIND_REMINDER
    if kind is not None:
        flow.kind, flow.preview = kind, preview
        if ask_deadline:
            flow.deadline = _detect_deadline(ctx, text)
        await _ask_area(ctx, flow)
        return
    buttons: list[Button] = [(KIND_ACTION, kind, label) for kind, label in KIND_LABELS.items()]
    await _ask(ctx, flow, STEP_KIND, fmt.card(fmt.Q_KIND, _content(flow)), [*buttons, CANCEL])


# --- Área ------------------------------------------------------------------------------------


async def _ask_area(ctx: Ctx, flow: Flow) -> None:
    available = areas.list_areas(ctx.conn)
    if not available:  # sin áreas que ofrecer no hay nada que preguntar
        flow.area_id = None
        await _after_area(ctx, flow)
        return
    buttons: list[Button] = [("a", area.id, fmt.label(area.name)) for area in available]
    buttons += [("a", 0, fmt.BTN_NO_AREA), CANCEL]
    text = fmt.card(fmt.Q_AREA, _content(flow), _details(ctx, flow))
    await _ask(ctx, flow, STEP_AREA, text, buttons)


async def _after_area(ctx: Ctx, flow: Flow) -> None:
    """Ya se sabe tipo y área: se termina (tarea, nota) o se sigue con la fecha (recordatorio)."""
    if flow.kind == KIND_TASK and flow.deadline is not None:
        await _ask_deadline(ctx, flow)
    elif flow.kind == KIND_TASK:
        tasks.set_area(ctx.conn, flow.task_id, flow.area_id, ctx.now)
        done = fmt.card(fmt.DONE_TASK, shown(flow.text), _area_line(ctx, flow.area_id))
        await _finish(ctx, flow, done)
    elif flow.kind == KIND_NOTE:
        notes.create_note(ctx.conn, flow.text, ctx.now, area_id=flow.area_id)
        tasks.close_as_converted(ctx.conn, flow.task_id, "converted_to_note", ctx.now)
        done = fmt.card(fmt.DONE_NOTE, shown(flow.text), _area_line(ctx, flow.area_id))
        await _finish(ctx, flow, done)
    else:
        result = _parse(ctx, flow.text)
        flow.title = strip_reminder_verb(result.title).strip() or flow.text
        await _apply_schedule(ctx, flow, result)


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


async def _ask_deadline(ctx: Ctx, flow: Flow) -> None:
    deadline = flow.deadline
    assert deadline is not None
    details = [
        *_details(ctx, flow),
        _when_line(ctx, deadline.when_utc, deadline.has_time, "Fecha"),
    ]
    text = fmt.card(fmt.Q_DEADLINE, shown(deadline.title), details)
    buttons: list[Button] = [("ly", None, fmt.BTN_YES), ("ln", None, fmt.BTN_NO), CANCEL]
    await _ask(ctx, flow, STEP_DEADLINE, text, buttons, tail=1)


async def _finish_task(ctx: Ctx, flow: Flow, with_deadline: bool) -> None:
    tasks.set_area(ctx.conn, flow.task_id, flow.area_id, ctx.now)
    deadline = flow.deadline
    if with_deadline and deadline is not None:
        tasks.set_title(ctx.conn, flow.task_id, deadline.title, ctx.now)
        tasks.set_due(ctx.conn, flow.task_id, deadline.when_utc, ctx.now)
        details = [
            *_area_line(ctx, flow.area_id),
            _when_line(ctx, deadline.when_utc, deadline.has_time, "Vence"),
        ]
        done = fmt.card(fmt.DONE_TASK, shown(deadline.title), details)
    else:
        done = fmt.card(fmt.DONE_TASK, shown(flow.text), _area_line(ctx, flow.area_id))
    await _finish(ctx, flow, done)


async def _on_deadline_yes(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _finish_task(ctx, flow, True)
    return True


async def _on_deadline_no(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _finish_task(ctx, flow, False)
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
        targets["h"] = (evening, fmt.etiqueta_hora("Hoy", evening, ctx.tz_name))
    tomorrow = reminders.tomorrow_target(ctx.conn, moment, ctx.tz_name)
    same_day = to_local(tomorrow, ctx.tz_name).date() == to_local(moment, ctx.tz_name).date()
    targets["m"] = (
        tomorrow,
        fmt.etiqueta_hora("Hoy" if same_day else "Mañana", tomorrow, ctx.tz_name),
    )
    return targets


async def _ask_when(ctx: Ctx, flow: Flow, note: str = fmt.HINT_WHEN) -> None:
    flow.candidates = ()
    quick: list[Button] = [(key, None, label) for key, (_, label) in _quick_targets(ctx).items()]
    text = fmt.card(fmt.Q_WHEN, _content(flow), _details(ctx, flow), note=note)
    await _ask(ctx, flow, STEP_WHEN, text, [*quick, AS_TASK, CANCEL])


def _question_title(ctx: Ctx, reason: str | None, candidates: tuple[datetime, ...]) -> str:
    if reason == "ambiguous_meridiem" and candidates:
        if len(candidates) == 1:
            return f"¿A las {fmt.hora(candidates[0], ctx.tz_name)}?"
        hour = fmt.hora(candidates[0], ctx.tz_name).split(":")[0]
        return f"¿A las {hour} am o pm?"
    if reason == "past":
        if candidates:
            when = fmt.fecha_larga(candidates[0], ctx.tz_name, ctx.now)
            return f"Esa fecha ya pasó. ¿La dejo para {when}?"
        return "Esa fecha ya pasó. Escribe otra."
    return fmt.PARSER_QUESTIONS.get(reason or "", fmt.PARSER_QUESTION_GENERIC)


async def _ask_when_question(ctx: Ctx, flow: Flow, result: ScheduleResult) -> None:
    """Pregunta del parser en la tarjeta: candidatos de 2 por fila; abajo, Otra fecha y Cancelar."""
    candidates = result.when.candidates if result.when is not None else ()
    flow.candidates = candidates
    title = _question_title(ctx, result.reason, candidates)
    buttons: list[Button] = [
        ("w", index, fmt.fecha_corta(moment, ctx.tz_name, ctx.now))
        for index, moment in enumerate(candidates)
    ]
    if result.reason in NO_DATE_BUTTONS:
        buttons.append(("n", None, NO_DATE_BUTTONS[result.reason]))
    if result.reason == "unsupported_date" and not candidates:
        buttons += [(key, None, label) for key, (_, label) in _quick_targets(ctx).items()]
    buttons += [("o", None, fmt.BTN_OTHER_DATE), CANCEL]
    text = fmt.card(title, _content(flow), _details(ctx, flow))
    await _ask(ctx, flow, STEP_WHEN, text, buttons)


async def _apply_schedule(ctx: Ctx, flow: Flow, result: ScheduleResult) -> None:
    """Qué hacer con lo que entendió el parser: guardar, previsualizar, preguntar o pedir fecha."""
    if result.kind == "once" and result.when is not None and result.when.when_utc is not None:
        await _propose(ctx, flow, result.when.when_utc, None, result.when.has_time)
    elif result.kind == "series" and result.series is not None:
        series = result.series
        assert series.first_at_utc is not None and series.rrule is not None
        await _propose(ctx, flow, series.first_at_utc, series.rrule, series.has_time)
    elif result.kind == "ask":
        await _ask_when_question(ctx, flow, result)
    else:
        await _ask_when(ctx, flow)


async def _propose(
    ctx: Ctx, flow: Flow, when_utc: datetime, rrule: str | None, has_time: bool
) -> None:
    """Una fecha ya resuelta: se guarda y se confirma (con Cambiar/Deshacer), salvo una repetición
    o un /recordar, que muestran primero la interpretación y esperan «Guardar»."""
    if rrule is None and not flow.preview:
        await _create(ctx, flow, when_utc, rrule, has_time)
        return
    flow.pending = Pending(when_utc, rrule, has_time)
    if rrule is not None:
        details = _schedule_details(ctx, flow.area_id, when_utc, rrule, has_time)
        text = fmt.card(fmt.Q_SAVE_SERIES, shown(flow.title), details)
    else:
        details = [_when_line(ctx, when_utc, has_time), *_area_line(ctx, flow.area_id)]
        text = fmt.card(fmt.Q_SAVE_REMINDER, shown(flow.title), details)
    await _ask(ctx, flow, STEP_SERIES, text, [("s", None, fmt.BTN_SAVE), CANCEL])


def _schedule_details(
    ctx: Ctx, area_id: int | None, when_utc: datetime, rrule: str | None, has_time: bool
) -> list[fmt.Html]:
    """Los datos de un recordatorio ya interpretado: Cuándo (o Repetición y Próxima) y Área."""
    if rrule is None:
        lines = [_when_line(ctx, when_utc, has_time)]
    else:
        lines = [
            fmt.detail("Repetición", describe_rrule(rrule)),
            _when_line(ctx, when_utc, has_time, "Próxima"),
        ]
    return [*lines, *_area_line(ctx, area_id)]


async def _create(
    ctx: Ctx, flow: Flow, when_utc: datetime, rrule: str | None, has_time: bool
) -> None:
    """Crea el recordatorio (cierra la tarea de bandeja en la misma transacción) y confirma."""
    try:
        reminder = tasks.convert_to_reminder(
            ctx.conn, flow.task_id, flow.title, when_utc, ctx.now, area_id=flow.area_id, rrule=rrule
        )
    except reminders.PastReminderError:  # la opción tardó tanto que ya pasó: jamás en el pasado
        await _ask_when(ctx, flow, f"{fmt.HINT_PAST} {fmt.HINT_WHEN}")
        return
    if reminder is None:  # la tarea ya no está abierta: no hay nada que convertir
        await _finish(ctx, flow, STALE_CHOICE_TEXT)
        return
    logger.info("Bandeja: tarea %s convertida en el recordatorio %s", flow.task_id, reminder.id)
    details = _schedule_details(ctx, reminder.area_id, when_utc, rrule, has_time)
    done = fmt.card(fmt.DONE_REMINDER, shown(reminder.text), details)
    ids = (reminder.id, flow.task_id)
    buttons = [
        Choice(encode_choice_id(ACTION_CHANGE, *ids), fmt.BTN_CHANGE),
        Choice(encode_choice_id(ACTION_UNDO, *ids), fmt.BTN_UNDO),
    ]
    await _finish(ctx, flow, done, buttons, (2,))


# --- Área nueva (/nuevaarea) -------------------------------------------------------------------


async def start_new_area(ctx: Ctx, name: str) -> None:
    """El nombre ya está validado: se pregunta la descripción (se puede omitir)."""
    await _drop_current_flow(ctx)
    flow = ctx.conversation.start(0, name, ctx.now, STEP_AREA_DESC)
    text = fmt.card(f"¿Qué cubre «{shown(name)}»?", note=fmt.NOTE_AREA_DESCRIPTION)
    await _ask(ctx, flow, STEP_AREA_DESC, text, [("d", None, fmt.BTN_SKIP), CANCEL])


async def _finish_area(ctx: Ctx, flow: Flow, description: str) -> None:
    try:
        area = areas.create_area(ctx.conn, flow.text, description, ctx.now)
    except areas.AreaError as error:  # p. ej. alguien creó el mismo nombre mientras tanto
        await _finish(ctx, flow, fmt.aviso(str(error)))
        return
    logger.info("Área creada id=%s", area.id)
    done = fmt.card(fmt.DONE_AREA, area.name, note=area.description or fmt.NOTE_NO_DESCRIPTION)
    await _finish(ctx, flow, done)


# --- Botones del flujo -----------------------------------------------------------------------


async def _on_kind(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if len(args) != 1 or args[0] not in KIND_LABELS:
        return False
    flow.kind = args[0]
    await _ask_area(ctx, flow)
    return True


async def _on_area(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if len(args) != 1 or not _is_id(args[0]):
        return False
    area_id = int(args[0])
    area = areas.get_area(ctx.conn, area_id) if area_id else None
    if area_id and (area is None or area.archived):
        return False
    flow.area_id = area_id or None
    await _after_area(ctx, flow)
    return True


async def _on_candidate(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if len(args) != 1 or not _is_id(args[0]) or int(args[0]) >= len(flow.candidates):
        return False
    await _propose(ctx, flow, flow.candidates[int(args[0])], None, True)
    return True


async def _on_quick(
    ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str], key: str
) -> bool:
    if args:
        return False
    target = _quick_targets(ctx).get(key)
    if target is None:  # "Hoy 6:00 pm" que se pulsó cuando ya había pasado
        await _ask_when(ctx, flow, f"{fmt.HINT_PAST} {fmt.HINT_WHEN}")
        return True
    await _propose(ctx, flow, target[0], None, True)
    return True


async def _on_write_other(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    await _ask_when(ctx, flow, fmt.HINT_WRITE_WHEN)
    return True


async def _on_no_date(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    flow.title = flow.text
    await _ask_when(ctx, flow)
    return True


async def _on_save(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    pending = flow.pending
    if args or pending is None:
        return False
    await _create(ctx, flow, pending.when_utc, pending.rrule, pending.has_time)
    return True


async def _on_skip_description(
    ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]
) -> bool:
    if args:
        return False
    await _finish_area(ctx, flow, "")
    return True


async def _on_better_as_task(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    """«Mejor como tarea»: queda como tarea (con el área elegida) y sin recordatorio."""
    if args:
        return False
    tasks.set_area(ctx.conn, flow.task_id, flow.area_id, ctx.now)
    done = fmt.card(fmt.DONE_TASK, shown(flow.text), _area_line(ctx, flow.area_id))
    await _finish(ctx, flow, done)
    return True


async def _on_cancel(ctx: Ctx, flow: Flow, choice: IncomingChoice, args: list[str]) -> bool:
    if args:
        return False
    note = fmt.NOTE_NO_AREA if flow.step == STEP_AREA_DESC else fmt.NOTE_IN_INBOX
    await _finish(ctx, flow, fmt.card(fmt.CANCELLED, shown(flow.text), note=note))
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


async def handle_flow_choice(ctx: Ctx, choice: IncomingChoice, parts: list[str]) -> str | None:
    """`in:FLUJO:ACCION[:ARG]`. Mal formado, de otro flujo o de otro paso = botón viejo."""
    handled = False
    if len(parts) >= 2 and _is_id(parts[0]):
        flow = ctx.conversation.get(int(parts[0]), ctx.now)
        action, args = parts[1], parts[2:]
        if flow is not None:
            if choice.message_ref is not None:
                flow.message_ref = choice.message_ref  # la tarjeta es el mensaje del botón
            if action in ("h", "m") and flow.step == STEP_WHEN:
                handled = await _on_quick(ctx, flow, choice, args, action)
            elif action in _FLOW_ACTIONS:
                step, handler = _FLOW_ACTIONS[action]
                if step is None or flow.step == step:
                    handled = await handler(ctx, flow, choice, args)
    if not handled:
        return await _stale(ctx, choice)
    ctx.conversation.last_press_id = choice.choice_id
    return None


# --- Deshacer y Cambiar ----------------------------------------------------------------------


async def handle_conversion_choice(
    ctx: Ctx, choice: IncomingChoice, action: str, parts: list[str]
) -> str | None:
    """`un:RECORDATORIO:TAREA` / `ch:RECORDATORIO:TAREA`. Viven en la base, no en la memoria."""
    if len(parts) != 2 or not all(_is_id(part) for part in parts):
        return await _stale(ctx, choice)
    reminder_id, task_id = int(parts[0]), int(parts[1])
    reminder = reminders.get_reminder(ctx.conn, reminder_id)
    task = tasks.get_task(ctx.conn, task_id)
    if reminder is None or task is None:
        return await _stale(ctx, choice)
    if not tasks.undo_reminder_conversion(ctx.conn, task_id, reminder_id, ctx.now):
        if choice.choice_id == ctx.conversation.last_press_id:
            return None  # doble pulsación: el mensaje ya quedó como debía
        flow = ctx.conversation.current(ctx.now)
        if flow is not None and flow.message_ref == choice.message_ref:
            return fmt.TOAST_STALE  # sobre la tarjeta viva no se pisa la pregunta vigente
        await show(ctx.channel, choice, fmt.NOT_UNDOABLE)
        return None
    ctx.conversation.last_press_id = choice.choice_id
    logger.info("Bandeja: recordatorio %s deshecho (tarea %s)", reminder_id, task_id)
    if action == ACTION_UNDO:
        text = fmt.state_line(fmt.UNDONE, shown(reminder.text), "vuelve a tu bandeja como tarea")
        await show(ctx.channel, choice, text)
        return None
    await _drop_current_flow(ctx)
    flow = ctx.conversation.start(task_id, task.source_text or task.title, ctx.now, STEP_WHEN)
    flow.kind, flow.area_id, flow.title = KIND_REMINDER, reminder.area_id, reminder.text
    flow.message_ref = choice.message_ref  # sigue en el mismo mensaje
    await _ask_when(ctx, flow)
    return None
