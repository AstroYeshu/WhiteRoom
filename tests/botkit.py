"""Arnés para probar la conversación de punta a punta con un canal falso.

Uso: `from tests.botkit import Bot, module_loop  # noqa: F401` y un fixture `bot(conn, clock)`.
Todas las pruebas de un módulo comparten UN bucle de asyncio (crear uno por prueba se colgaba
a veces en Windows; ver `tests/test_reminders_outage.py`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field

import pytest

from asistente.bot import handlers
from asistente.bot.choices import MAX_CHOICE_ID_BYTES
from asistente.bot.conversation import Conversation
from asistente.channels.base import Choice, IncomingChoice, IncomingMessage
from tests.fakes import FakeChannel

TZ = "America/Mexico_City"
OWNER = 12345
REF = "77"

_runner: asyncio.Runner | None = None


@pytest.fixture(scope="module", autouse=True)
def module_loop():
    global _runner
    with asyncio.Runner() as runner:
        _runner = runner
        yield runner
    _runner = None


def run(coroutine: Coroutine):
    assert _runner is not None, "falta importar el fixture module_loop"
    return _runner.run(coroutine)


@dataclass
class LoggingChannel(FakeChannel):
    """Guarda TODO en orden y comprueba que ningún id de botón pase de 64 bytes."""

    log: list[tuple[str, str, list[Choice]]] = field(default_factory=list)

    async def send_text(self, to, text, kind="reply"):
        self.log.append(("text", text, []))
        await super().send_text(to, text, kind)

    async def send_choices(self, to, text, choices, kind="reply"):
        for choice in choices:
            assert len(choice.id.encode("utf-8")) <= MAX_CHOICE_ID_BYTES, choice.id
        self.log.append(("choices", text, list(choices)))
        await super().send_choices(to, text, choices, kind)

    async def edit_text(self, to, message_ref, text):
        self.log.append(("edit", text, []))
        await super().edit_text(to, message_ref, text)


class Bot:
    def __init__(self, conn, clock) -> None:
        self.conn, self.clock = conn, clock
        self.channel = LoggingChannel()
        self.conversation = Conversation()

    def say(self, text: str, user: int = OWNER) -> None:
        event = IncomingMessage("fake", str(user), text)
        run(
            handlers.handle_message(
                event, self.channel, OWNER, self.conn, self.clock, TZ, self.conversation
            )
        )

    def press(self, choice_id: str, user: int = OWNER) -> None:
        event = IncomingChoice("fake", str(user), choice_id, REF)
        run(
            handlers.handle_choice(
                event, self.channel, OWNER, self.conn, self.clock, TZ, self.conversation
            )
        )

    def restart(self) -> None:
        """Simula reiniciar el proceso: se pierde el estado en memoria, no la base."""
        self.conversation = Conversation()

    @property
    def last(self) -> tuple[str, str, list[Choice]]:
        return self.channel.log[-1]

    @property
    def question(self) -> tuple[str, list[Choice]]:
        """El último mensaje CON botones."""
        for kind, text, choices in reversed(self.channel.log):
            if kind == "choices":
                return text, choices
        raise AssertionError("no hubo ninguna pregunta con botones")

    def choice_id(self, label_part: str) -> str:
        _, choices = self.question
        matches = [c.id for c in choices if label_part in c.label]
        assert len(matches) == 1, (label_part, [c.label for c in choices])
        return matches[0]

    def tap(self, label_part: str) -> None:
        self.press(self.choice_id(label_part))

    def labels(self) -> list[str]:
        return [c.label for c in self.question[1]]

    # --- Lo enviado, para las pruebas de comandos -------------------------------------------

    def messages(self) -> list[str]:
        """Todos los mensajes nuevos (texto o con botones), sin las ediciones."""
        return [text for kind, text, _ in self.channel.log if kind != "edit"]

    def edits(self) -> list[str]:
        return [text for kind, text, _ in self.channel.log if kind == "edit"]

    def reply(self, text: str) -> str:
        """Dice `text` y devuelve el último mensaje enviado como respuesta."""
        before = len(self.channel.log)
        self.say(text)
        new = self.channel.log[before:]
        assert new, f"sin respuesta a {text!r}"
        return new[-1][1]

    def buttons_of(self, text_part: str) -> dict[str, str]:
        """{etiqueta: id} del mensaje con botones cuyo texto contiene `text_part`."""
        for kind, text, choices in reversed(self.channel.log):
            if kind == "choices" and text_part in text:
                return {choice.label: choice.id for choice in choices}
        raise AssertionError(f"ningún mensaje con botones contiene {text_part!r}")
