"""Arnés para probar la conversación de punta a punta con un canal falso.

Uso: `from tests.botkit import Bot, module_loop  # noqa: F401` y un fixture `bot(conn, clock)`.
Todas las pruebas de un módulo comparten UN bucle de asyncio (crear uno por prueba se colgaba
a veces en Windows; ver `tests/test_reminders_outage.py`).

El canal falso se comporta como Telegram: cada mensaje enviado tiene una referencia (`m1`, `m2`...),
editarlo cambia su texto y sus botones, y pulsar un botón llega con la referencia del mensaje donde
estaba ese botón (también un botón viejo: Telegram lo seguiría mostrando en ese mensaje).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field

import pytest

from asistente.bot import handlers
from asistente.bot.conversation import Conversation
from asistente.channels.base import Choice, IncomingChoice, IncomingMessage
from asistente.choices import MAX_CHOICE_ID_BYTES
from tests.fakes import FakeChannel

TZ = "America/Mexico_City"
OWNER = 12345
REF = "77"  # referencia para un id de botón que nunca se mostró

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
    """Guarda TODO en orden y comprueba que ningún id de botón pase de 64 bytes.

    `log` = (tipo, texto, botones) con tipo "text" | "choices" | "edit"; `refs` va en paralelo con
    la referencia del mensaje de cada entrada. `id_refs` recuerda en qué mensaje se mostró cada id.
    `editable=False` simula un canal que no puede editar (`edit_text` devuelve False).
    """

    log: list[tuple[str, str, list[Choice]]] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    id_refs: dict[str, str] = field(default_factory=dict)
    editable: bool = True
    _count: int = 0

    def _new_ref(self) -> str:
        self._count += 1
        return f"m{self._count}"

    def _remember(self, choices, ref: str, layout) -> None:
        for choice in choices:
            assert len(choice.id.encode("utf-8")) <= MAX_CHOICE_ID_BYTES, choice.id
            self.id_refs[choice.id] = ref
        if layout is not None:
            assert sum(layout) == len(choices), (layout, len(choices))

    async def send_text(self, to, text, kind="reply"):
        ref = self._new_ref()
        self.log.append(("text", text, []))
        self.refs.append(ref)
        await super().send_text(to, text, kind)
        return ref

    async def send_choices(self, to, text, choices, kind="reply", layout=None):
        ref = self._new_ref()
        self._remember(choices, ref, layout)
        self.log.append(("choices", text, list(choices)))
        self.refs.append(ref)
        await super().send_choices(to, text, choices, kind, layout)
        return ref

    async def edit_text(self, to, message_ref, text, choices=None, layout=None):
        if not self.editable:
            return False
        if choices:
            self._remember(choices, message_ref, layout)
        self.log.append(("edit", text, list(choices or [])))
        self.refs.append(message_ref)
        await super().edit_text(to, message_ref, text, choices, layout)
        return True


class Bot:
    def __init__(self, conn, clock, editable: bool = True, runtime=None) -> None:
        self.conn, self.clock = conn, clock
        self.runtime = runtime  # el estado de ejecución de /estado (None: no disponible)
        self.channel = LoggingChannel(editable=editable)
        self.conversation = Conversation()
        self.toasts: list[str | None] = []  # un aviso breve (o None) por cada pulsación

    def say(self, text: str, user: int = OWNER) -> None:
        event = IncomingMessage("fake", str(user), text)
        run(
            handlers.handle_message(
                event,
                self.channel,
                OWNER,
                self.conn,
                self.clock,
                TZ,
                self.conversation,
                runtime=self.runtime,
            )
        )

    def press(self, choice_id: str, user: int = OWNER) -> str | None:
        """Pulsa un botón. Devuelve el aviso breve (toast) con que se respondió, o None."""
        ref = self.channel.id_refs.get(choice_id, REF)
        event = IncomingChoice("fake", str(user), choice_id, ref)
        toast = run(
            handlers.handle_choice(
                event, self.channel, OWNER, self.conn, self.clock, TZ, self.conversation
            )
        )
        self.toasts.append(toast)
        return toast

    def restart(self) -> None:
        """Simula reiniciar el proceso: se pierde el estado en memoria, no la base."""
        self.conversation = Conversation()

    @property
    def last(self) -> tuple[str, str, list[Choice]]:
        return self.channel.log[-1]

    @property
    def question(self) -> tuple[str, list[Choice]]:
        """El último mensaje (nuevo o editado) CON botones."""
        for _kind, text, choices in reversed(self.channel.log):
            if choices:
                return text, choices
        raise AssertionError("no hubo ninguna pregunta con botones")

    @property
    def question_ref(self) -> str:
        for index in range(len(self.channel.log) - 1, -1, -1):
            if self.channel.log[index][2]:
                return self.channel.refs[index]
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

    # --- Lo enviado, para las pruebas de comandos y de tarjetas -----------------------------

    def messages(self) -> list[str]:
        """Los mensajes NUEVOS (texto o con botones), sin las ediciones."""
        return [text for kind, text, _ in self.channel.log if kind != "edit"]

    def sent_count(self) -> int:
        return len(self.messages())

    def edits(self) -> list[str]:
        return [text for kind, text, _ in self.channel.log if kind == "edit"]

    def text_of(self, ref: str) -> str:
        """El texto ACTUAL de un mensaje (el último que se le puso)."""
        for index in range(len(self.channel.log) - 1, -1, -1):
            if self.channel.refs[index] == ref:
                return self.channel.log[index][1]
        raise AssertionError(f"no hay un mensaje {ref}")

    def reply(self, text: str) -> str:
        """Dice `text` y devuelve el último mensaje enviado como respuesta."""
        before = len(self.channel.log)
        self.say(text)
        new = self.channel.log[before:]
        assert new, f"sin respuesta a {text!r}"
        return new[-1][1]

    def buttons_of(self, text_part: str) -> dict[str, str]:
        """{etiqueta: id} del mensaje con botones cuyo texto contiene `text_part`."""
        for _kind, text, choices in reversed(self.channel.log):
            if choices and text_part in text:
                return {choice.label: choice.id for choice in choices}
        raise AssertionError(f"ningún mensaje con botones contiene {text_part!r}")
