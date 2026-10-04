"""Comandos del dueño: /hoy, /pendientes, /recordatorios, /recordar, /tarea, /nota, /areas,
/nuevaarea. Independientes de la plataforma: reciben un `Ctx` y el texto tras el comando.

El texto del usuario NUNCA va al log; sí los ids y los códigos estables (motivos de parada).
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from asistente.bot import inbox
from asistente.bot.choices import encode_choice_id
from asistente.bot.inbox import Ctx
from asistente.bot.ui import STALE_CHOICE_TEXT, show, shown
from asistente.channels.base import Choice, IncomingChoice
from asistente.core import areas, reminders, tasks
from asistente.parsing.dates import format_when
from asistente.timeutil import from_utc_iso, local_to_utc, to_local

logger = logging.getLogger(__name__)

ACTION_TASK_DONE = "tk_done"
ACTION_TASK_DROP = "tk_drop"
PENDING_LIMIT = 10  # tareas de /pendientes: cada una es un mensaje con botones
TODAY_LIMIT = 15  # líneas por sección de /hoy
REMINDERS_LIMIT = 20

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


def _clock_text(moment: datetime, ctx: Ctx) -> str:
    """ "5:00 pm" (la hora de format_when, sin el día)."""
    return format_when(moment, ctx.tz_name, ctx.now).rpartition(", ")[2]


def _area_suffix(ctx: Ctx, area_id: int | None) -> str:
    area = areas.get_area(ctx.conn, area_id) if area_id is not None else None
    return f" [{area.name}]" if area is not None else ""


async def _area_filter(ctx: Ctx, args: str) -> tuple[bool, int | None]:
    """(sigue, area_id). Sin argumento no hay filtro; un área desconocida se avisa y se corta."""
    name = args.strip()
    if not name:
        return True, None
    area = areas.find_area_by_name(ctx.conn, name)
    if area is None:
        await ctx.channel.send_text(
            ctx.user_ref,
            f"No encuentro el área «{shown(name)}». Escribe /areas para ver las que hay.",
        )
        return False, None
    return True, area.id


def _more(lines: list[str], limit: int) -> list[str]:
    return (
        lines[:limit]
        if len(lines) <= limit
        else [*lines[:limit], f"...y {len(lines) - limit} más."]
    )


# --- /hoy ------------------------------------------------------------------------------------


async def today(ctx: Ctx, args: str) -> None:
    ok, area_id = await _area_filter(ctx, args)
    if not ok:
        return
    moment = ctx.now()
    today_local = to_local(moment, ctx.tz_name).date()
    # El día termina a las 00:00 LOCALES de mañana (no a medianoche UTC).
    day_end = local_to_utc(datetime.combine(today_local + timedelta(days=1), time(0)), ctx.tz_name)

    task_lines = []
    for task in tasks.list_due_before(ctx.conn, day_end, area_id):
        assert task.due_at_utc is not None
        due = from_utc_iso(task.due_at_utc)
        if to_local(due, ctx.tz_name).date() < today_local:
            when = f"vencida: {format_when(due, ctx.tz_name, ctx.now)}"
        else:
            when = f"hoy, {_clock_text(due, ctx)}"
        task_lines.append(f"- {task.title} ({when}){_area_suffix(ctx, task.area_id)}")

    reminder_lines = []
    for reminder in reminders.list_pending(ctx.conn):
        fire = from_utc_iso(reminder.fire_at_utc)
        if fire >= day_end or (area_id is not None and reminder.area_id != area_id):
            continue
        if to_local(fire, ctx.tz_name).date() < today_local:
            when = format_when(fire, ctx.tz_name, ctx.now)
        else:
            when = _clock_text(fire, ctx)
        stopped = " (detenido)" if reminder.stopped else ""
        line = f"- {when}: {reminder.text}{_area_suffix(ctx, reminder.area_id)}{stopped}"
        reminder_lines.append(line)

    header = format_when(moment, ctx.tz_name, ctx.now).rpartition(", ")[0]
    lines = [f"Hoy, {header}"]
    if task_lines:
        lines += ["Tareas:", *_more(task_lines, TODAY_LIMIT)]
    if reminder_lines:
        lines += ["Recordatorios:", *_more(reminder_lines, TODAY_LIMIT)]
    if not task_lines and not reminder_lines:
        lines.append("No tienes nada para hoy.")
    inbox_count = tasks.count_inbox(ctx.conn) if area_id is None else 0
    if inbox_count:
        lines.append(f"{inbox_count} en bandeja sin área")
    await ctx.channel.send_text(ctx.user_ref, "\n".join(lines))


# --- /pendientes ---------------------------------------------------------------------------------


async def pending(ctx: Ctx, args: str) -> None:
    ok, area_id = await _area_filter(ctx, args)
    if not ok:
        return
    open_tasks = tasks.list_open(ctx.conn, area_id, limit=10_000)
    if not open_tasks:
        await ctx.channel.send_text(ctx.user_ref, "No tienes tareas pendientes.")
        return
    await ctx.channel.send_text(ctx.user_ref, f"Pendientes ({len(open_tasks)}):")
    for task in open_tasks[:PENDING_LIMIT]:
        text = f"{task.title}{_area_suffix(ctx, task.area_id)}"
        if task.due_at_utc:
            due = format_when(from_utc_iso(task.due_at_utc), ctx.tz_name, ctx.now)
            text += f" (vence: {due})"
        await ctx.channel.send_choices(
            ctx.user_ref,
            text,
            [
                Choice(encode_choice_id(ACTION_TASK_DONE, task.id), "Hecha"),
                Choice(encode_choice_id(ACTION_TASK_DROP, task.id), "Descartar"),
            ],
        )
    extra = len(open_tasks) - PENDING_LIMIT
    if extra > 0:
        await ctx.channel.send_text(
            ctx.user_ref, f"Hay {extra} más. Filtra por área: /pendientes nombre."
        )


async def handle_task_choice(
    ctx: Ctx, choice: IncomingChoice, action: str, parts: list[str]
) -> None:
    """`tk_done:ID` / `tk_drop:ID`. Pulsar dos veces o sobre una tarea ya cerrada no da error."""
    task = None
    if len(parts) == 1 and parts[0].isascii() and parts[0].isdigit():
        task = tasks.get_task(ctx.conn, int(parts[0]))
    if task is None:
        await show(ctx.channel, choice, STALE_CHOICE_TEXT)
        return
    if action == ACTION_TASK_DONE:
        closed, label = tasks.mark_done(ctx.conn, task.id, ctx.now), "Hecha"
    else:
        closed, label = tasks.drop_task(ctx.conn, task.id, ctx.now), "Descartada"
    if closed:
        logger.info("Tarea %s: %s", task.id, label.lower())
        await show(ctx.channel, choice, f"{label}: {task.title}")
    else:
        await show(ctx.channel, choice, f"Esta tarea ya no está abierta: {task.title}")


# --- /recordatorios -----------------------------------------------------------------------------


def _reminder_line(ctx: Ctx, reminder: reminders.Reminder) -> str:
    when = format_when(from_utc_iso(reminder.fire_at_utc), ctx.tz_name, ctx.now)
    line = f"- {when}: {reminder.text}{_area_suffix(ctx, reminder.area_id)}"
    if reminder.rrule:
        line += f" ({inbox.describe_rrule(reminder.rrule)})"
    if reminder.stopped:
        code = reminder.stop_reason or ""
        reason = stop_reason_text(code)
        if reason is None:  # el código crudo solo al log, nunca al usuario
            logger.warning(
                "Recordatorio %s detenido con un motivo desconocido: %r", reminder.id, code
            )
            reason = UNKNOWN_STOP_TEXT
        line += f" (detenido: {reason})"
    return line


async def reminders_list(ctx: Ctx, args: str) -> None:
    pending_reminders = reminders.list_pending(ctx.conn)
    if not pending_reminders:
        await ctx.channel.send_text(ctx.user_ref, "No tienes recordatorios pendientes.")
        return
    lines = [_reminder_line(ctx, reminder) for reminder in pending_reminders]
    text = "\n".join([f"Recordatorios pendientes ({len(lines)}):", *_more(lines, REMINDERS_LIMIT)])
    await ctx.channel.send_text(ctx.user_ref, text)


# --- /recordar, /tarea, /nota --------------------------------------------------------------------

REMIND_USAGE = (
    "Escribe /recordar seguido de qué y cuándo, por ejemplo: /recordar mañana 8 am llevar tarea"
)
TASK_USAGE = "Escribe /tarea seguido de la tarea, por ejemplo: /tarea comprar pan"
NOTE_USAGE = (
    "Escribe /nota seguido de la nota, por ejemplo: /nota la clave del wifi está en el router"
)
NEW_AREA_USAGE = "Escribe /nuevaarea seguido del nombre, por ejemplo: /nuevaarea Salud"


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


# --- /areas y /nuevaarea -----------------------------------------------------------------


async def areas_list(ctx: Ctx, args: str) -> None:
    available = areas.list_areas(ctx.conn)
    if not available:
        await ctx.channel.send_text(ctx.user_ref, "No hay áreas. Crea una con /nuevaarea nombre.")
        return
    lines = [
        f"- {area.name}" + ("" if area.description.strip() else " (sin descripción)")
        for area in available
    ]
    await ctx.channel.send_text(ctx.user_ref, "\n".join(["Áreas:", *lines]))


async def new_area(ctx: Ctx, args: str) -> None:
    if not args.strip():
        await ctx.channel.send_text(ctx.user_ref, NEW_AREA_USAGE)
        return
    try:
        name = areas.validate_new_name(ctx.conn, args)
    except areas.AreaError as error:
        await ctx.channel.send_text(ctx.user_ref, str(error))
        return
    await inbox.start_new_area(ctx, name)


COMMANDS = {
    "hoy": today,
    "pendientes": pending,
    "recordatorios": reminders_list,
    "recordar": remind,
    "tarea": new_task,
    "nota": new_note,
    "areas": areas_list,
    "nuevaarea": new_area,
}
