"""Contrato común de los canales (consola, Telegram, un posible WhatsApp futuro).

El resto del sistema solo conoce estos tipos; nunca sabe en qué plataforma corre.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


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


class Channel(Protocol):
    """Todo lo que el sistema envía pasa por aquí.

    `kind` ∈ `reply | reminder | briefing`: deja que cada canal decida CÓMO enviar.
    """

    async def send_text(self, to: str, text: str, kind: str = "reply") -> None: ...

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None: ...


MessageCallback = Callable[[IncomingMessage], Awaitable[None]]
ChoiceCallback = Callable[[IncomingChoice], Awaitable[None]]
