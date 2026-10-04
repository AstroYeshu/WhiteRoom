"""Piezas de presentación compartidas por los manejadores (independientes de la plataforma)."""

from __future__ import annotations

from asistente.channels.base import Channel, IncomingChoice
from asistente.formato import STALE_CHOICE

STALE_CHOICE_TEXT = STALE_CHOICE
MAX_SHOWN_CHARS = 120  # cuánto del texto del usuario se repite en un mensaje


def shown(text: str) -> str:
    """El texto del usuario recortado para repetirlo en un mensaje."""
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_SHOWN_CHARS else flat[: MAX_SHOWN_CHARS - 1] + "…"


async def show(channel: Channel, choice: IncomingChoice, text: str) -> None:
    """Edita el mensaje del botón (sin teclado); si el canal no puede, manda uno nuevo."""
    if choice.message_ref is None:
        await channel.send_text(choice.user_ref, text)
    else:
        await channel.edit_text(choice.user_ref, choice.message_ref, text)
