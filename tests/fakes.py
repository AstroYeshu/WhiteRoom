"""Canal falso para pruebas: guarda lo que se enviaría en lugar de enviarlo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from asistente.channels.base import Choice


@dataclass
class FakeChannel:
    texts: list[tuple[str, str, str]] = field(default_factory=list)  # (to, text, kind)
    choices: list[tuple[str, str, list[Choice], str]] = field(default_factory=list)

    async def send_text(self, to: str, text: str, kind: str = "reply") -> None:
        self.texts.append((to, text, kind))

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None:
        self.choices.append((to, text, choices, kind))

    @property
    def sent_anything(self) -> bool:
        return bool(self.texts or self.choices)


@dataclass
class FakeClock:
    """Reloj falso: se llama como `now()` y se adelanta a mano."""

    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


class ScriptedChannel(FakeChannel):
    """Canal que puede fallar a voluntad: `fail_if(texto)` devuelve la excepción a lanzar o None."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_if = lambda text: None
        self.attempts: list[str] = []  # todo intento de envío, haya salido o no

    async def send_choices(
        self, to: str, text: str, choices: list[Choice], kind: str = "reply"
    ) -> None:
        self.attempts.append(text)
        error = self.fail_if(text)
        if error is not None:
            raise error
        await super().send_choices(to, text, choices, kind)

    def always_fail_with(self, error: Exception | None) -> None:
        self.fail_if = lambda text: error
