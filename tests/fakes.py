"""Canal falso para pruebas: guarda lo que se enviaría en lugar de enviarlo."""

from __future__ import annotations

from dataclasses import dataclass, field

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
