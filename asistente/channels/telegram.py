"""Canal de Telegram. ÚNICO módulo que importa la librería de Telegram.

Convierte lo recibido en `IncomingMessage` / `IncomingChoice` y descarta en silencio
a cualquier usuario que no sea `ALLOWED_USER_ID` (ni siquiera responde al botón).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Sequence
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
    TICK_INTERVAL_SECONDS,
    Choice,
    ChoiceCallback,
    IncomingChoice,
    IncomingMessage,
    MessageCallback,
    PermanentChannelError,
    TickCallback,
    TransientChannelError,
    UnclassifiedChannelError,
    run_tick_safely,
)
from asistente.formato import plain, to_html

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
CANT_PARSE_REASON = "bad_request:cant_parse_entities"

T = TypeVar("T")


def build_keyboard(
    choices: list[Choice], layout: Sequence[int] | None = None
) -> InlineKeyboardMarkup:
    """Botones en filas según `layout` (uno por fila si no hay); el `id` va en `callback_data`."""
    sizes = tuple(layout) if layout is not None else (1,) * len(choices)
    if sum(sizes) != len(choices) or any(size < 1 for size in sizes):
        raise ValueError("La distribución de botones no suma el número de botones")
    buttons = [InlineKeyboardButton(c.label, callback_data=c.id) for c in choices]
    rows, start = [], 0
    for size in sizes:
        rows.append(buttons[start : start + size])
        start += size
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

    async def send_text(self, to: str, text: str, kind: str = "reply") -> str | None:
        return await self._send(chat_id=int(to), text=text)

    async def send_choices(
        self,
        to: str,
        text: str,
        choices: list[Choice],
        kind: str = "reply",
        layout: Sequence[int] | None = None,
    ) -> str | None:
        keyboard = build_keyboard(choices, layout)
        return await self._send(chat_id=int(to), text=text, reply_markup=keyboard)

    async def _send(self, text: str, **kwargs: object) -> str | None:
        """Envía en HTML; si Telegram no puede leer el formato, UNA vez más en texto plano.

        Un aviso no puede perderse por un problema de formato. Solo `cant_parse_entities` reintenta;
        si el texto plano también falla, el error es permanente como cualquier otro BadRequest.
        """
        try:
            sent = await _translated(
                self._application.bot.send_message(text=to_html(text), parse_mode="HTML", **kwargs)
            )
        except PermanentChannelError as error:
            if error.reason != CANT_PARSE_REASON:
                raise
            logger.warning("Telegram no leyó el formato: se reenvía en texto plano")
            sent = await _translated(self._application.bot.send_message(text=plain(text), **kwargs))
        message_id = getattr(sent, "message_id", None)
        return None if message_id is None else str(message_id)

    async def edit_text(
        self,
        to: str,
        message_ref: str,
        text: str,
        choices: list[Choice] | None = None,
        layout: Sequence[int] | None = None,
    ) -> bool:
        """Edita el mensaje: con `choices` le pone ese teclado; sin ellos Telegram quita el viejo.

        Es cosmético: "message is not modified" (mismo texto) cuenta como éxito y cualquier otro
        fallo se registra por tipo, nunca con el texto, sin propagarse (devuelve False).
        """
        ids: dict[str, object] = {"chat_id": int(to), "message_id": int(message_ref)}
        if choices:
            ids["reply_markup"] = build_keyboard(choices, layout)
        try:
            try:
                await self._application.bot.edit_message_text(
                    text=to_html(text), parse_mode="HTML", **ids
                )
            except tg_error.BadRequest as error:
                if _bad_request_reason(error) != CANT_PARSE_REASON:
                    raise
                logger.warning("Telegram no leyó el formato: se edita en texto plano")
                await self._application.bot.edit_message_text(text=plain(text), **ids)
        except tg_error.BadRequest as error:
            if "message is not modified" in str(error).lower():
                return True
            logger.warning("No se pudo editar el mensaje: %s", type(error).__name__)
            return False
        except tg_error.TelegramError as error:
            logger.warning("No se pudo editar el mensaje: %s", type(error).__name__)
            return False
        return True

    # --- Entrada -------------------------------------------------------------------

    def run_polling(
        self,
        on_message: MessageCallback,
        on_choice: ChoiceCallback,
        on_tick: TickCallback,
        tick_seconds: float = TICK_INTERVAL_SECONDS,
    ) -> None:
        """Arranca el long polling (bloqueante). No abre puertos.

        `on_tick` corre cada `tick_seconds` (y al arrancar) en el `job_queue` de la librería.
        """

        async def _tick_job(context: ContextTypes.DEFAULT_TYPE) -> None:
            await run_tick_safely(on_tick)

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
            try:
                await query.answer()  # siempre al dueño: quita el relojito del botón
            except tg_error.TelegramError as error:
                # Cosmético: la pulsación del dueño no se pierde por no poder responderla.
                logger.warning("No se pudo responder a la pulsación: %s", type(error).__name__)
            message = getattr(query, "message", None)
            message_ref = None if message is None else str(message.message_id)
            await on_choice(IncomingChoice(CHANNEL_NAME, user_ref, query.data or "", message_ref))

        async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            # Solo el tipo de error: el texto del mensaje del usuario nunca se registra.
            logger.error("Error en Telegram: %s", type(context.error).__name__)

        self._application.add_handler(MessageHandler(filters.TEXT, _on_text))
        self._application.add_handler(CallbackQueryHandler(_on_callback))
        self._application.add_error_handler(_on_error)
        job_queue = self._application.job_queue
        if job_queue is None:  # falta el extra `job-queue`: sin él no habría recordatorios
            raise RuntimeError("python-telegram-bot sin el extra job-queue")
        job_queue.run_repeating(
            _tick_job,
            interval=tick_seconds,
            first=0,  # un tick al arrancar: recupera lo vencido durante una caída
            name="reminder_tick",
            # Una sola instancia a la vez; los disparos atrasados se funden en uno.
            job_kwargs={"max_instances": 1, "coalesce": True},
        )
        self._application.run_polling()
