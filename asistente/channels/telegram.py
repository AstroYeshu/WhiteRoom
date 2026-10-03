"""Canal de Telegram. ÚNICO módulo que importa la librería de Telegram.

Convierte lo recibido en `IncomingMessage` / `IncomingChoice` y descarta en silencio
a cualquier usuario que no sea `ALLOWED_USER_ID` (ni siquiera responde al botón).
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
)

logger = logging.getLogger(__name__)

CHANNEL_NAME = "telegram"
HTTP_TIMEOUT_SECONDS = 10.0


def build_keyboard(choices: list[Choice]) -> InlineKeyboardMarkup:
    """Un botón por fila; el `id` de la opción viaja como `callback_data`."""
    rows = [[InlineKeyboardButton(c.label, callback_data=c.id)] for c in choices]
    return InlineKeyboardMarkup(rows)


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
        await self._application.bot.send_message(chat_id=int(to), text=text)

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None:
        await self._application.bot.send_message(
            chat_id=int(to), text=text, reply_markup=build_keyboard(choices)
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
