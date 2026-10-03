"""Canal de consola: para `--dry-run` y pruebas. No usa red ni secretos."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from asistente.channels.base import (
    Choice,
    ChoiceCallback,
    IncomingChoice,
    IncomingMessage,
    MessageCallback,
)

CHANNEL_NAME = "console"
EXIT_COMMANDS = {"/salir", "/exit"}


class ConsoleChannel:
    """Imprime las respuestas y lee los mensajes de la terminal.

    Las opciones (`Choice`) se muestran como lista numerada; escribir el número la elige.
    """

    def __init__(
        self,
        user_ref: str,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._user_ref = user_ref
        self._input = input_fn
        self._output = output_fn
        self._pending: list[Choice] = []

    async def send_text(self, to: str, text: str, kind: str = "reply") -> None:
        prefix = "" if kind == "reply" else f"[{kind}] "
        self._output(f"{prefix}{text}")

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None:
        await self.send_text(to, text, kind)
        self._pending = list(choices)
        for number, choice in enumerate(choices, start=1):
            self._output(f"  {number}) {choice.label}")

    def _parse(self, line: str) -> IncomingMessage | IncomingChoice:
        """Un número válido con opciones pendientes es una elección; lo demás, un mensaje."""
        if line.isdigit() and 1 <= int(line) <= len(self._pending):
            choice = self._pending[int(line) - 1]
            self._pending = []
            return IncomingChoice(CHANNEL_NAME, self._user_ref, choice.id)
        self._pending = []
        return IncomingMessage(CHANNEL_NAME, self._user_ref, line)

    async def serve(self, on_message: MessageCallback, on_choice: ChoiceCallback) -> None:
        """Bucle principal: lee líneas hasta `/salir` o fin de entrada (Ctrl+Z / Ctrl+D)."""
        self._output("Modo consola (dry-run). Escribe /ayuda; /salir para terminar.")
        while True:
            try:
                line = (await asyncio.to_thread(self._input, "> ")).strip()
            except EOFError:
                return
            if line.lower() in EXIT_COMMANDS:
                return
            if not line:
                continue
            event = self._parse(line)
            if isinstance(event, IncomingChoice):
                await on_choice(event)
            else:
                await on_message(event)
