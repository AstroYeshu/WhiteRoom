"""Conversación independiente de la plataforma.

Los canales convierten lo recibido en `IncomingMessage` / `IncomingChoice` y llaman aquí.
En la Fase 0 solo existen `/start` y `/ayuda`.
"""

from __future__ import annotations

import logging

from asistente.bot.auth import is_allowed
from asistente.channels.base import Channel, IncomingChoice, IncomingMessage

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


async def handle_choice(choice: IncomingChoice, channel: Channel, allowed_user_id: int) -> None:
    if not is_allowed(choice.user_ref, allowed_user_id):
        _reject(choice.user_ref)
        return
    # Aún no hay opciones que ofrecer; cualquier botón viejo se responde con cortesía.
    await channel.send_text(choice.user_ref, STALE_CHOICE_TEXT)
