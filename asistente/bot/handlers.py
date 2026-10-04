"""Conversación independiente de la plataforma.

Los canales convierten lo recibido en `IncomingMessage` / `IncomingChoice` y llaman aquí.
Hoy: `/start`, `/ayuda` y los botones de los recordatorios (`rem_done`, `rem_snooze`,
`rem_tomorrow`). Pulsar un botón EDITA el mensaje (texto nuevo, sin teclado).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from asistente.bot.auth import is_allowed
from asistente.bot.choices import decode_choice_id
from asistente.channels.base import Channel, IncomingChoice, IncomingMessage
from asistente.core import reminders
from asistente.parsing.dates import format_when
from asistente.timeutil import Clock, to_local

logger = logging.getLogger(__name__)

START_TEXT = (
    "¡Hola! Soy tu asistente personal.\n"
    "Todavía estoy en construcción: por ahora solo respondo a comandos básicos.\n"
    "Escribe /ayuda para verlos."
)
HELP_TEXT = "Comandos disponibles:\n/start - saludo\n/ayuda - esta lista"
UNKNOWN_COMMAND_TEXT = "No conozco ese comando. Escribe /ayuda para ver los disponibles."
NOT_SAVED_TEXT = (
    "Todavía no guardo mensajes: tareas, notas y recordatorios llegan en la siguiente fase. "
    "Escribe /ayuda para ver lo que sí puedo hacer."
)
STALE_CHOICE_TEXT = "Esa opción ya no está disponible."
NOT_ACTIVE_TEXT = "Este recordatorio ya no está activo."
SNOOZE_CHOICES_MINUTES = (reminders.SNOOZE_SHORT_MINUTES, reminders.SNOOZE_LONG_MINUTES)


def _command_name(text: str) -> str | None:
    """`/Start@mi_bot arg` -> `start`. Devuelve None si el texto no es un comando."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    return stripped.split()[0][1:].split("@")[0].lower()


def _reject(user_ref: str) -> None:
    # Silencio total hacia el extraño; solo queda constancia del ID (nunca del texto).
    logger.info("Mensaje ignorado de usuario no autorizado: user_ref=%s", user_ref)


async def handle_message(msg: IncomingMessage, channel: Channel, allowed_user_id: int) -> None:
    if not is_allowed(msg.user_ref, allowed_user_id):
        _reject(msg.user_ref)
        return

    command = _command_name(msg.text)
    if command == "start":
        reply = START_TEXT
    elif command == "ayuda":
        reply = HELP_TEXT
    elif command is not None:
        reply = UNKNOWN_COMMAND_TEXT
    else:
        reply = NOT_SAVED_TEXT
    await channel.send_text(msg.user_ref, reply)


def _is_id(part: str) -> bool:
    return part.isascii() and part.isdigit()


def _parse_reminder_choice(choice_id: str) -> tuple[str, int, int | None] | None:
    """`rem_done:7` / `rem_snooze:7:10` / `rem_tomorrow:7` -> (acción, id, minutos).

    Devuelve None si no es un botón de recordatorio o viene mal formado (también un botón viejo
    con una duración que ya no se ofrece): nunca se toca nada con un id dudoso.
    """
    action, parts = decode_choice_id(choice_id)
    if action in (reminders.ACTION_DONE, reminders.ACTION_TOMORROW):
        if len(parts) == 1 and _is_id(parts[0]):
            return action, int(parts[0]), None
    elif action == reminders.ACTION_SNOOZE:
        if len(parts) == 2 and _is_id(parts[0]) and _is_id(parts[1]):
            if int(parts[1]) in SNOOZE_CHOICES_MINUTES:
                return action, int(parts[0]), int(parts[1])
    return None


def _when_text(target: datetime, tz_name: str, now: Clock) -> str:
    """ "hoy, 3:40 pm" si es hoy; si no, el día completo ("domingo 4 de octubre, 9:00 am")."""
    full = format_when(target, tz_name, now)
    if to_local(target, tz_name).date() == to_local(now(), tz_name).date():
        return f"hoy, {full.rpartition(', ')[2]}"
    return full


async def _show(channel: Channel, choice: IncomingChoice, text: str) -> None:
    """Edita el mensaje del botón (sin teclado); si el canal no puede, manda uno nuevo."""
    if choice.message_ref is None:
        await channel.send_text(choice.user_ref, text)
    else:
        await channel.edit_text(choice.user_ref, choice.message_ref, text)


async def _handle_reminder_choice(
    choice: IncomingChoice,
    request: tuple[str, int, int | None],
    channel: Channel,
    conn: sqlite3.Connection,
    now: Clock,
    tz_name: str,
) -> None:
    action, reminder_id, minutes = request
    reminder = reminders.get_reminder(conn, reminder_id)
    if reminder is None:
        await _show(channel, choice, NOT_ACTIVE_TEXT)
        return

    if action == reminders.ACTION_DONE:
        if reminders.mark_done(conn, reminder_id):
            await _show(channel, choice, f"✅ Hecho: {reminder.text}")
            return
    else:
        if action == reminders.ACTION_SNOOZE and minutes is not None:
            target = reminders.snooze(conn, reminder_id, timedelta(minutes=minutes), now)
        else:
            target = reminders.snooze_until_tomorrow(conn, reminder_id, now, tz_name)
        if target is not None:
            when = _when_text(target, tz_name, now)
            await _show(channel, choice, f"⏱ Pospuesto para {when}: {reminder.text}")
            return

    # Pulsó dos veces, o el recordatorio ya se hizo, se canceló o se pospuso: sin error.
    await _show(channel, choice, f"⏰ {reminder.text} (ya no está activo)")


async def handle_choice(
    choice: IncomingChoice,
    channel: Channel,
    allowed_user_id: int,
    conn: sqlite3.Connection,
    now: Clock,
    tz_name: str,
) -> None:
    if not is_allowed(choice.user_ref, allowed_user_id):
        _reject(choice.user_ref)
        return
    request = _parse_reminder_choice(choice.choice_id)
    if request is None:
        # Botón viejo o desconocido: se responde con cortesía y no se toca nada.
        await channel.send_text(choice.user_ref, STALE_CHOICE_TEXT)
        return
    await _handle_reminder_choice(choice, request, channel, conn, now, tz_name)
