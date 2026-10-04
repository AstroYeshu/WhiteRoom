"""Canal de consola: para `--dry-run` y pruebas. No usa red ni secretos."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence

from asistente.bot.format import plain
from asistente.channels.base import (
    TICK_INTERVAL_SECONDS,
    Choice,
    ChoiceCallback,
    IncomingChoice,
    IncomingMessage,
    MessageCallback,
    TickCallback,
    run_tick_safely,
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
        self._output(f"{prefix}{plain(text)}")

    async def send_choices(
        self,
        to: str,
        text: str,
        choices: list[Choice],
        kind: str = "reply",
        layout: Sequence[int] | None = None,
    ) -> None:
        await self.send_text(to, text, kind)
        self._pending = list(choices)
        for number, choice in enumerate(choices, start=1):
            self._output(f"  {number}) {choice.label}")

    async def edit_text(self, to: str, message_ref: str, text: str) -> None:
        """La consola no puede reescribir lo ya impreso: muestra el texto nuevo marcado."""
        self._output(f"[editado] {plain(text)}")

    def _parse(self, line: str) -> IncomingMessage | IncomingChoice:
        """Un número válido con opciones pendientes es una elección; lo demás, un mensaje."""
        if line.isdigit() and 1 <= int(line) <= len(self._pending):
            choice = self._pending[int(line) - 1]
            self._pending = []
            return IncomingChoice(CHANNEL_NAME, self._user_ref, choice.id)
        self._pending = []
        return IncomingMessage(CHANNEL_NAME, self._user_ref, line)

    async def serve(
        self,
        on_message: MessageCallback,
        on_choice: ChoiceCallback,
        on_tick: TickCallback,
        tick_interval: float = TICK_INTERVAL_SECONDS,
    ) -> None:
        """Bucle principal: lee líneas hasta `/salir` o fin de entrada (Ctrl+Z / Ctrl+D).

        El tick de recordatorios corre en una tarea aparte (uno al arrancar y luego cada
        `tick_interval` s); como espera a que termine cada tick, nunca se solapa.
        """
        ticker = asyncio.create_task(self._tick_loop(on_tick, tick_interval))
        try:
            await self._read_loop(on_message, on_choice)
        finally:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker

    @staticmethod
    async def _tick_loop(on_tick: TickCallback, interval: float) -> None:
        while True:
            await run_tick_safely(on_tick)
            await asyncio.sleep(interval)

    async def _read_loop(self, on_message: MessageCallback, on_choice: ChoiceCallback) -> None:
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
