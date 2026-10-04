"""Estado de la conversación en MEMORIA (un solo usuario, un solo flujo a la vez).

Un "flujo" es lo que queda a medias tras un mensaje libre: ¿qué es?, ¿qué área?, ¿cuándo?
Vive solo en memoria: si el proceso se reinicia o pasan 10 minutos sin actividad se pierde, y
no pasa nada grave porque el mensaje YA está guardado como tarea sin área (la bandeja).

Cada botón de un flujo lleva el id del flujo; un botón de un flujo viejo se reconoce y se ignora.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from asistente.timeutil import Clock

FLOW_TTL = timedelta(minutes=10)  # sin actividad durante este tiempo, el flujo caduca

STEP_KIND = "kind"  # ¿tarea, recordatorio o nota?
STEP_AREA = "area"  # ¿en qué área?
STEP_WHEN = "when"  # ¿cuándo? (botones o un texto con la fecha)
STEP_SERIES = "series"  # vista previa de un recordatorio (o repetición): guardar o cancelar
STEP_DEADLINE = "deadline"  # /tarea con fecha: ¿es la fecha límite?
STEP_AREA_DESC = "area_desc"  # /nuevaarea: se espera la descripción (o Omitir)


@dataclass(frozen=True)
class Pending:
    """Un recordatorio ya interpretado que espera el «Guardar» del usuario."""

    when_utc: datetime
    rrule: str | None
    has_time: bool


@dataclass(frozen=True)
class Deadline:
    """La fecha que /tarea encontró en el texto, a la espera del Sí/No del usuario."""

    when_utc: datetime
    has_time: bool
    title: str  # el texto sin la fecha


@dataclass
class Flow:
    id: int
    task_id: int  # la tarea de bandeja en la que se guardó el mensaje (0 = ninguna)
    text: str  # el mensaje original (nunca va al log)
    expires_at: datetime
    step: str = STEP_KIND
    kind: str | None = None  # "t" tarea, "r" recordatorio, "n" nota
    area_id: int | None = None
    title: str = ""  # texto del recordatorio
    candidates: tuple[datetime, ...] = ()  # opciones de fecha ya resueltas (UTC)
    preview: bool = False  # /recordar: SIEMPRE se muestra la interpretación antes de guardar
    pending: Pending | None = None
    deadline: Deadline | None = None


class Conversation:
    """Guarda, a lo sumo, un flujo. Empezar uno nuevo descarta el anterior."""

    def __init__(self) -> None:
        self._flow: Flow | None = None
        self._last_id = 0

    def _next_id(self, now: Clock) -> int:
        # Parte de la hora actual: tras un reinicio no choca con botones de la vida anterior.
        self._last_id = max(self._last_id + 1, int(now().timestamp()))
        return self._last_id

    def start(self, task_id: int, text: str, now: Clock, step: str = STEP_KIND) -> Flow:
        self._flow = Flow(self._next_id(now), task_id, text, now() + FLOW_TTL, step)
        return self._flow

    def renew(self, flow: Flow, now: Clock) -> None:
        """Se va a hacer una pregunta nueva: id nuevo (los botones de la anterior quedan viejos)
        y caducidad contada desde ahora."""
        flow.id = self._next_id(now)
        flow.expires_at = now() + FLOW_TTL

    def current(self, now: Clock) -> Flow | None:
        """El flujo vigente, o None si no hay o ya caducó (y entonces se olvida)."""
        if self._flow is not None and now() >= self._flow.expires_at:
            self._flow = None
        return self._flow

    def get(self, flow_id: int, now: Clock) -> Flow | None:
        """El flujo vigente SOLO si es el de ese id (un botón viejo no encuentra nada)."""
        flow = self.current(now)
        return flow if flow is not None and flow.id == flow_id else None

    def clear(self) -> None:
        self._flow = None
