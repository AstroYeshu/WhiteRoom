"""Comandos del dueño: /hoy, /pendientes, /recordatorios, /recordar, /tarea, /nota, /areas,
/nuevaarea. Independientes de la plataforma: reciben un `Ctx` y el texto tras el comando.

Los textos salen de `formato.py` (con todo el texto del usuario escapado). El texto del usuario
NUNCA va al log; sí los ids y los códigos estables (motivos de parada).
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from asistente import formato as fmt
from asistente.bot import inbox
from asistente.bot.inbox import Ctx
from asistente.bot.ui import show
from asistente.channels.base import Choice, IncomingChoice
from asistente.choices import encode_choice_id
from asistente.core import areas, reminders, runtime, tasks
from asistente.timeutil import from_utc_iso, local_to_utc, to_local

logger = logging.getLogger(__name__)

ACTION_PENDING = "pd"  # pd:o:AREA:TAREA | pd:h:AREA:TAREA | pd:d:AREA:TAREA | pd:b:AREA
VERB_OPEN, VERB_DONE, VERB_DROP, VERB_BACK = "o", "h", "d", "b"
PENDING_LIMIT = fmt.PENDING_LIMIT
NUMBERS_PER_ROW = 5

# Códigos estables de `reminders.stop_reason` -> lenguaje claro. Nunca se muestra el código crudo.
STOP_REASON_TEXT = {
    "permanent:bot_blocked": "el bot está bloqueado en tu chat",
    "permanent:chat_not_found": "no se encontró tu chat",
    "permanent:message_too_long": "el mensaje era demasiado largo",
    "permanent:bad_request:cant_parse_entities": "Telegram no pudo leer el formato del texto",
    "permanent:bad_request:empty_text": "el texto estaba vacío",
    "permanent:bad_request:button_data_invalid": "un botón no era válido",
    "permanent:bad_request:other": "Telegram rechazó el mensaje",
    "horizon:telegram_down": "Telegram no respondió durante 24 horas",
    "legacy": "se detuvo en una versión anterior",
}
# Familias con sufijo variable (la clase del error): todas se explican igual.
STOP_REASON_FAMILIES = ("permanent:telegram_error:", "permanent:unexpected:")
UNEXPECTED_STOP_TEXT = "error inesperado al enviar"
UNKNOWN_STOP_TEXT = "motivo desconocido"


def stop_reason_text(code: str) -> str | None:
    """El motivo en lenguaje claro, o None si el código no se conoce."""
    if code in STOP_REASON_TEXT:
        return STOP_REASON_TEXT[code]
    if code.startswith(STOP_REASON_FAMILIES):
        return UNEXPECTED_STOP_TEXT
    return None


# --- Utilidades ------------------------------------------------------------------------------


def _area_name(ctx: Ctx, area_id: int | None) -> str | None:
    area = areas.get_area(ctx.conn, area_id) if area_id is not None else None
    return area.name if area is not None else None


async def _area_filter(ctx: Ctx, args: str) -> tuple[bool, int | None]:
    """(sigue, area_id). Sin argumento no hay filtro; un área desconocida se avisa y se corta."""
    name = args.strip()
    if not name:
        return True, None
    area = areas.find_area_by_name(ctx.conn, name)
    if area is None:
        message = f"No encuentro el área «{fmt.clip(name)}». Escribe /areas para ver las que hay."
        await ctx.channel.send_text(ctx.user_ref, fmt.aviso(message))
        return False, None
    return True, area.id


# --- /hoy ------------------------------------------------------------------------------------


async def today(ctx: Ctx, args: str) -> None:
    ok, area_id = await _area_filter(ctx, args)
    if not ok:
        return
    moment = ctx.now()
    today_local = to_local(moment, ctx.tz_name).date()
    # El día termina a las 00:00 LOCALES de mañana (no a medianoche UTC).
    day_end = local_to_utc(datetime.combine(today_local + timedelta(days=1), time(0)), ctx.tz_name)

    task_items: list[fmt.Html] = []
    for task in tasks.list_due_before(ctx.conn, day_end, area_id):
        assert task.due_at_utc is not None
        due = from_utc_iso(task.due_at_utc)
        when = fmt.fecha_corta(due, ctx.tz_name, ctx.now)
        if to_local(due, ctx.tz_name).date() < today_local:
            when = f"vencida {when}"
        area = None if area_id is not None else _area_name(ctx, task.area_id)
        task_items.append(fmt.bullet(fmt.clip(task.title), when, area))

    reminder_items: list[fmt.Html] = []
    for reminder in reminders.list_pending(ctx.conn):
        fire = from_utc_iso(reminder.fire_at_utc)
        if fire >= day_end or (area_id is not None and reminder.area_id != area_id):
            continue
        area = None if area_id is not None else _area_name(ctx, reminder.area_id)
        when = fmt.fecha_corta(fire, ctx.tz_name, ctx.now)
        stopped = "detenido" if reminder.stopped else None
        reminder_items.append(fmt.bullet(when, fmt.clip(reminder.text), area, stopped))

    title = f"Hoy{fmt.SEP}{fmt.dia_largo(moment, ctx.tz_name, ctx.now)}"
    if area_id is not None:
        title += f"{fmt.SEP}{_area_name(ctx, area_id)}"
    blocks: list[str | None] = []
    if task_items:
        blocks.append(fmt.section("Tareas", task_items, fmt.TODAY_LIMIT))
    if reminder_items:
        blocks.append(fmt.section("Recordatorios", reminder_items, fmt.TODAY_LIMIT))
    if not blocks:
        blocks.append(fmt.EMPTY_TODAY)
    inbox_count = tasks.count_inbox(ctx.conn) if area_id is None else 0
    if inbox_count:
        blocks.append(f"{inbox_count} en bandeja sin área")
    await ctx.channel.send_text(ctx.user_ref, fmt.screen(title, *blocks))


# --- /pendientes: un solo mensaje ----------------------------------------------------------------


def _pending_view(
    ctx: Ctx, area_id: int | None, note: str | None = None
) -> tuple[fmt.Html, list[Choice], tuple[int, ...] | None]:
    """La lista (texto, un botón por número y su distribución); sin tareas, sin botones."""
    open_tasks = tasks.list_open(ctx.conn, area_id, limit=10_000)
    shown_tasks = open_tasks[:PENDING_LIMIT]
    rows = []
    for task in shown_tasks:
        due = from_utc_iso(task.due_at_utc) if task.due_at_utc else None
        rows.append(
            fmt.PendingRow(
                task.title,
                None if area_id is not None else _area_name(ctx, task.area_id),
                fmt.fecha_corta(due, ctx.tz_name, ctx.now) if due else None,
            )
        )
    text = fmt.pending_list(len(open_tasks), rows, _area_name(ctx, area_id), note)
    choices = [
        Choice(encode_choice_id(ACTION_PENDING, VERB_OPEN, area_id or 0, task.id), str(number))
        for number, task in enumerate(shown_tasks, start=1)
    ]
    layout = fmt.rows_layout(len(choices), per_row=NUMBERS_PER_ROW) if choices else None
    return text, choices, layout


async def pending(ctx: Ctx, args: str) -> None:
    ok, area_id = await _area_filter(ctx, args)
    if not ok:
        return
    text, choices, layout = _pending_view(ctx, area_id)
    if choices:
        await ctx.channel.send_choices(ctx.user_ref, text, choices, layout=layout)
    else:
        await ctx.channel.send_text(ctx.user_ref, text)


def _ids(parts: list[str]) -> list[int] | None:
    if all(part.isascii() and part.isdigit() for part in parts):
        return [int(part) for part in parts]
    return None


async def _refresh_list(
    ctx: Ctx, choice: IncomingChoice, area_id: int | None, note: str | None = None
) -> None:
    text, choices, layout = _pending_view(ctx, area_id, note)
    await show(ctx.channel, choice, text, choices or None, layout)


async def handle_pending_choice(ctx: Ctx, choice: IncomingChoice, parts: list[str]) -> str | None:
    """`pd:VERBO:AREA[:TAREA]`: abrir una tarea, Hecha, Descartar o Volver a la lista. No guarda
    estado: todo viaja en el id, así que los botones sobreviven a un reinicio. Devuelve el aviso
    breve si el botón ya no aplica (tarea cerrada, id mal formado)."""
    verb = parts[0] if parts else ""
    ids = _ids(parts[1:])
    needs_task = verb in (VERB_OPEN, VERB_DONE, VERB_DROP)
    if verb not in (VERB_OPEN, VERB_DONE, VERB_DROP, VERB_BACK) or ids is None:
        return fmt.TOAST_STALE
    if len(ids) != (2 if needs_task else 1):
        return fmt.TOAST_STALE
    area_id = ids[0] or None
    if area_id is not None and areas.get_area(ctx.conn, area_id) is None:
        area_id = None
    if verb == VERB_BACK:
        await _refresh_list(ctx, choice, area_id)
        return None
    task = tasks.get_task(ctx.conn, ids[1])
    if task is None or task.status != "open":  # ya no está abierta: aviso y la lista al día
        await _refresh_list(ctx, choice, area_id)
        return fmt.TOAST_STALE
    if verb == VERB_OPEN:
        due = from_utc_iso(task.due_at_utc) if task.due_at_utc else None
        row = fmt.PendingRow(
            task.title,
            _area_name(ctx, task.area_id),
            fmt.fecha_corta(due, ctx.tz_name, ctx.now) if due else None,
        )
        ids_for = (area_id or 0, task.id)
        buttons = [
            Choice(encode_choice_id(ACTION_PENDING, VERB_DONE, *ids_for), fmt.BTN_DONE),
            Choice(encode_choice_id(ACTION_PENDING, VERB_DROP, *ids_for), fmt.BTN_DROP),
            Choice(encode_choice_id(ACTION_PENDING, VERB_BACK, area_id or 0), fmt.BTN_BACK),
        ]
        await show(ctx.channel, choice, fmt.pending_detail(row), buttons, (2, 1))
        return None
    if verb == VERB_DONE:
        closed, state = tasks.mark_done(ctx.conn, task.id, ctx.now), "Hecha"
    else:
        closed, state = tasks.drop_task(ctx.conn, task.id, ctx.now), "Descartada"
    if not closed:
        await _refresh_list(ctx, choice, area_id)
        return fmt.TOAST_STALE
    logger.info("Tarea %s: %s", task.id, state.lower())
    note = fmt.state_line(state, fmt.clip(task.title))
    await _refresh_list(ctx, choice, area_id, note)
    return None


# --- /recordatorios: pendientes y detenidos por separado -----------------------------------------


def _reminder_item(ctx: Ctx, reminder: reminders.Reminder) -> fmt.Html:
    when = fmt.fecha_corta(from_utc_iso(reminder.fire_at_utc), ctx.tz_name, ctx.now)
    area = _area_name(ctx, reminder.area_id)
    if reminder.stopped:
        code = reminder.stop_reason or ""
        reason = stop_reason_text(code)
        if reason is None:  # el código crudo solo al log, nunca al usuario
            logger.warning(
                "Recordatorio %s detenido con un motivo desconocido: %r", reminder.id, code
            )
            reason = UNKNOWN_STOP_TEXT
        return fmt.bullet(when, fmt.clip(reminder.text, 80), area, f"Motivo: {reason}")
    repeat = inbox.describe_rrule(reminder.rrule) if reminder.rrule else None
    return fmt.bullet(when, fmt.clip(reminder.text, 80), area, repeat)


async def reminders_list(ctx: Ctx, args: str) -> None:
    pending_items: list[fmt.Html] = []
    stopped_items: list[fmt.Html] = []
    for reminder in reminders.list_pending(ctx.conn):
        target = stopped_items if reminder.stopped else pending_items
        target.append(_reminder_item(ctx, reminder))
    blocks: list[str | None] = []
    if pending_items:
        title = f"Pendientes ({len(pending_items)})"
        blocks.append(fmt.section(title, pending_items, fmt.LIST_LIMIT))
    if stopped_items:
        title = f"Detenidos ({len(stopped_items)})"
        blocks.append(fmt.section(title, stopped_items, fmt.LIST_LIMIT))
    if not blocks:
        blocks.append(fmt.NO_REMINDERS)
    await ctx.channel.send_text(ctx.user_ref, fmt.screen("Recordatorios", *blocks))


# --- /recordar, /tarea, /nota --------------------------------------------------------------------

REMIND_USAGE = fmt.aviso(
    "Escribe /recordar seguido de qué y cuándo, por ejemplo: /recordar mañana 8 am llevar tarea"
)
TASK_USAGE = fmt.aviso("Escribe /tarea seguido de la tarea, por ejemplo: /tarea comprar pan")
NOTE_USAGE = fmt.aviso(
    "Escribe /nota seguido de la nota, por ejemplo: /nota la clave del wifi está en el router"
)
NEW_AREA_USAGE = fmt.aviso("Escribe /nuevaarea seguido del nombre, por ejemplo: /nuevaarea Salud")


async def remind(ctx: Ctx, args: str) -> None:
    if not args.strip():
        await ctx.channel.send_text(ctx.user_ref, REMIND_USAGE)
        return
    await inbox.capture_as(ctx, args, inbox.KIND_REMINDER, preview=True)


async def new_task(ctx: Ctx, args: str) -> None:
    if not args.strip():
        await ctx.channel.send_text(ctx.user_ref, TASK_USAGE)
        return
    await inbox.capture_as(ctx, args, inbox.KIND_TASK, ask_deadline=True)


async def new_note(ctx: Ctx, args: str) -> None:
    if not args.strip():
        await ctx.channel.send_text(ctx.user_ref, NOTE_USAGE)
        return
    await inbox.capture_as(ctx, args, inbox.KIND_NOTE)


# --- /areas y /nuevaarea -------------------------------------------------------------------------


async def areas_list(ctx: Ctx, args: str) -> None:
    available = areas.list_areas(ctx.conn)
    if not available:
        await ctx.channel.send_text(ctx.user_ref, fmt.screen("Áreas", fmt.NO_AREAS))
        return
    items = [
        fmt.bullet(area.name, None if area.description.strip() else "sin descripción")
        for area in available
    ]
    await ctx.channel.send_text(
        ctx.user_ref, fmt.screen(f"Áreas ({len(items)})", fmt.block(*items))
    )


async def new_area(ctx: Ctx, args: str) -> None:
    if not args.strip():
        await ctx.channel.send_text(ctx.user_ref, NEW_AREA_USAGE)
        return
    try:
        name = areas.validate_new_name(ctx.conn, args)
    except areas.AreaError as error:
        await ctx.channel.send_text(ctx.user_ref, fmt.aviso(str(error)))
        return
    await inbox.start_new_area(ctx, name)


# --- /estado: salud del bot, sin textos del usuario ----------------------------------------------


async def status(ctx: Ctx, args: str) -> None:
    if ctx.runtime is None:
        await ctx.channel.send_text(ctx.user_ref, fmt.STATUS_UNAVAILABLE)
        return
    report = runtime.collect(ctx.conn, ctx.runtime, ctx.now())

    def when(moment: datetime | None, none_text: str) -> str:
        return fmt.fecha_corta(moment, ctx.tz_name, ctx.now) if moment else none_text

    ticked = (
        "todavía ninguno"
        if report.last_tick_at is None
        else "hace " + fmt.duration_text((ctx.now() - report.last_tick_at).total_seconds())
    )
    size = "no disponible" if report.db_size_bytes is None else fmt.size_text(report.db_size_bytes)
    reminder_counts = fmt.SEP.join(
        (
            fmt.counted(report.pending, "pendiente", "pendientes"),
            fmt.counted(report.stopped, "detenido", "detenidos"),
        )
    )
    lines = [
        fmt.detail("Entorno", report.bot_env),
        fmt.detail("Arrancó", when(report.started_at, "")),
        fmt.detail("Encendido", fmt.duration_text(report.uptime_seconds)),
        fmt.detail("Último ciclo", ticked),
        fmt.detail("Último aviso enviado", when(report.last_fired_at, "ninguno todavía")),
        fmt.detail("Recordatorios", reminder_counts),
        fmt.detail("Esquema", f"versión {report.schema_version}"),
        fmt.detail("Base de datos", size),
    ]
    await ctx.channel.send_text(ctx.user_ref, fmt.screen("Estado", fmt.block(*lines)))


COMMANDS = {
    "hoy": today,
    "pendientes": pending,
    "recordatorios": reminders_list,
    "recordar": remind,
    "tarea": new_task,
    "nota": new_note,
    "areas": areas_list,
    "nuevaarea": new_area,
    "estado": status,
}
