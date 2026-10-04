"""Canal de Telegram. ÚNICO módulo que importa la librería de Telegram.

Convierte lo recibido en `IncomingMessage` / `IncomingChoice` y descarta en silencio
a cualquier usuario que no sea `ALLOWED_USER_ID` (ni siquiera responde al botón).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import timedelta
from typing import TypeVar

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram import error as tg_error
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from asistente.bot.auth import is_allowed
from asistente.channels.base import (
    Choice,
    ChoiceCallback,
    IncomingChoice,
    IncomingMessage,
    MessageCallback,
    PermanentChannelError,
    TransientChannelError,
    UnclassifiedChannelError,
)

logger = logging.getLogger(__name__)

CHANNEL_NAME = "telegram"
HTTP_TIMEOUT_SECONDS = 10.0

# Mensajes de BadRequest conocidos -> código estable. Cualquier otro es "bad_request:other": el
# mensaje de Telegram nunca pasa al código (podría traer texto arbitrario, emojis o URLs).
KNOWN_BAD_REQUESTS = (
    ("can't parse entities", "bad_request:cant_parse_entities"),
    ("message text is empty", "bad_request:empty_text"),
    ("button_data_invalid", "bad_request:button_data_invalid"),
)
OTHER_BAD_REQUEST = "bad_request:other"

T = TypeVar("T")


def build_keyboard(choices: list[Choice]) -> InlineKeyboardMarkup:
    """Un botón por fila; el `id` de la opción viaja como `callback_data`."""
    rows = [[InlineKeyboardButton(c.label, callback_data=c.id)] for c in choices]
    return InlineKeyboardMarkup(rows)


def seconds_from(value: int | float | timedelta) -> float:
    """Espera en segundos: la librería entrega `retry_after` como `int` o como `timedelta`."""
    return value.total_seconds() if isinstance(value, timedelta) else float(value)


def _bad_request_reason(error: tg_error.BadRequest) -> str:
    message = str(error).lower()
    if "chat not found" in message:
        return "chat_not_found"
    if "message is too long" in message:
        return "message_too_long"
    for fragment, code in KNOWN_BAD_REQUESTS:
        if fragment in message:
            return code
    return OTHER_BAD_REQUEST


def translate_error(error: tg_error.TelegramError) -> Exception:
    """Traduce un error de Telegram a las clases del motor (el motor no conoce la librería).

    - Salud del canal (red, timeout, límite de envíos, 5xx, token): `TransientChannelError`.
    - Culpa del mensaje o del chat (bot bloqueado, `BadRequest` conocido):
      `PermanentChannelError`, solo para ese recordatorio.
    - Cualquier otro error de Telegram (Conflict...): `UnclassifiedChannelError`; el motor decide
      por evidencia, igual que con una excepción que no es de Telegram.

    El orden importa: `BadRequest` y `TimedOut` heredan de `NetworkError`.
    """
    if isinstance(error, tg_error.RetryAfter):
        return TransientChannelError("rate_limited", retry_after=seconds_from(error.retry_after))
    if isinstance(error, tg_error.Forbidden):
        return PermanentChannelError("bot_blocked")
    if isinstance(error, tg_error.BadRequest):
        return PermanentChannelError(_bad_request_reason(error))
    if isinstance(error, tg_error.TimedOut):
        return TransientChannelError("timeout")
    if isinstance(error, tg_error.NetworkError):
        return TransientChannelError("network")
    if isinstance(error, tg_error.InvalidToken):
        return TransientChannelError("invalid_token")  # lo arregla el dueño; nada se pierde
    return UnclassifiedChannelError(f"telegram_error:{type(error).__name__}")


async def _translated(call: Awaitable[T]) -> T:
    """Espera `call` y convierte los errores de Telegram; los demás pasan tal cual."""
    try:
        return await call
    except tg_error.TelegramError as error:
        raise translate_error(error) from error


class TelegramChannel:
    def __init__(self, token: str, allowed_user_id: int) -> None:
        self._allowed_user_id = allowed_user_id
        self._application: Application = (
            ApplicationBuilder()
            .token(token)
            .connect_timeout(HTTP_TIMEOUT_SECONDS)
            .read_timeout(HTTP_TIMEOUT_SECONDS)
            .write_timeout(HTTP_TIMEOUT_SECONDS)
            .pool_timeout(HTTP_TIMEOUT_SECONDS)
            .build()
        )

    # --- Salida (interfaz Channel) -------------------------------------------------

    async def send_text(self, to: str, text: str, kind: str = "reply") -> None:
        await _translated(self._application.bot.send_message(chat_id=int(to), text=text))

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None:
        await _translated(
            self._application.bot.send_message(
                chat_id=int(to), text=text, reply_markup=build_keyboard(choices)
            )
        )

    # --- Entrada -------------------------------------------------------------------

    def run_polling(self, on_message: MessageCallback, on_choice: ChoiceCallback) -> None:
        """Arranca el long polling (bloqueante). No abre puertos."""

        async def _on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if update.effective_user is None or update.message is None:
                return
            user_ref = str(update.effective_user.id)
            if not is_allowed(user_ref, self._allowed_user_id):
                logger.info("Update ignorado de usuario no autorizado: user_ref=%s", user_ref)
                return
            await on_message(IncomingMessage(CHANNEL_NAME, user_ref, update.message.text or ""))

        async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            query = update.callback_query
            if query is None or update.effective_user is None:
                return
            user_ref = str(update.effective_user.id)
            if not is_allowed(user_ref, self._allowed_user_id):
                logger.info("Update ignorado de usuario no autorizado: user_ref=%s", user_ref)
                return  # sin query.answer(): silencio total
            await query.answer()  # quita el relojito del botón
            await on_choice(IncomingChoice(CHANNEL_NAME, user_ref, query.data or ""))

        async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            # Solo el tipo de error: el texto del mensaje del usuario nunca se registra.
            logger.error("Error en Telegram: %s", type(context.error).__name__)

        self._application.add_handler(MessageHandler(filters.TEXT, _on_text))
        self._application.add_handler(CallbackQueryHandler(_on_callback))
        self._application.add_error_handler(_on_error)
        self._application.run_polling()
