"""Contrato común de los canales (consola, Telegram, un posible WhatsApp futuro).

El resto del sistema solo conoce estos tipos; nunca sabe en qué plataforma corre.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from asistente.config import DEFAULT_TICK_SECONDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Choice:
    """Una opción que el usuario puede elegir (cada canal decide cómo dibujarla)."""

    id: str  # corto, p. ej. "done:42"
    label: str


@dataclass(frozen=True)
class IncomingMessage:
    channel: str
    user_ref: str
    text: str


@dataclass(frozen=True)
class IncomingChoice:
    channel: str
    user_ref: str
    choice_id: str
    message_ref: str | None = None  # el mensaje que llevaba el botón (None si el canal no edita)


class ChannelError(Exception):
    """Error al enviar. Cada canal traduce los errores de su plataforma a una de estas clases.

    `reason` es un código corto y estable (p. ej. "bot_blocked", "timeout"); NUNCA lleva el
    texto del usuario, porque es lo único que el motor de recordatorios registra en el log.
    """

    def __init__(self, reason: str = "unknown") -> None:
        super().__init__(reason)
        self.reason = reason


class TransientChannelError(ChannelError):
    """Falla pasajera (red, timeout, plataforma caída): vale la pena reintentar.

    `retry_after` (segundos) es la espera mínima que pidió la plataforma, si la hubo.
    """

    def __init__(self, reason: str = "unknown", retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.retry_after = retry_after


class UnclassifiedChannelError(ChannelError):
    """Error de la plataforma que no es claramente del canal ni del mensaje (p. ej. Conflict).

    Ni transitorio ni permanente: el motor decide por evidencia. Si otros recordatorios sí salen
    en el mismo tick, la culpa es de esa fila y se detiene; si ninguno sale, se trata como
    pasajero. `reason` es un código estable con la clase del error (`telegram_error:Conflict`).
    """


class PermanentChannelError(ChannelError):
    """Falla que no se arregla reintentando (bot bloqueado, chat no encontrado)."""


class Channel(Protocol):
    """Todo lo que el sistema envía pasa por aquí.

    `kind` es `reply`, `reminder` o `briefing`: deja que cada canal decida CÓMO enviar.
    """

    async def send_text(self, to: str, text: str, kind: str = "reply") -> None: ...

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None: ...

    async def edit_text(self, to: str, message_ref: str, text: str) -> None:
        """Cambia el texto de un mensaje ya enviado y le quita los botones. Es cosmético:
        no debe lanzar errores (la acción del usuario ya se hizo)."""
        ...


MessageCallback = Callable[[IncomingMessage], Awaitable[None]]
ChoiceCallback = Callable[[IncomingChoice], Awaitable[None]]
TickCallback = Callable[[], Awaitable[object]]  # el tick de recordatorios (cada 30 s)

TICK_INTERVAL_SECONDS = (
    DEFAULT_TICK_SECONDS  # por defecto; el real viene de TICK_SECONDS (SPEC 8.3)
)


async def run_tick_safely(on_tick: TickCallback) -> None:
    """Un fallo dentro del tick se registra (solo el tipo, nunca texto) y no mata al job."""
    try:
        await on_tick()
    except Exception as error:  # noqa: BLE001 - el siguiente tick debe poder correr
        logger.error("Fallo en el tick de recordatorios: %s", type(error).__name__)
