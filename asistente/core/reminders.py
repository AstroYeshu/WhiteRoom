"""Motor de recordatorios: crea, envía, pospone y reintenta. NO usa ningún LLM.

Este módulo no importa nada de `llm/` ni de `classify/` (lo comprueba un test de AST):
los recordatorios deben sonar aunque se caiga cualquier API de IA.

Garantía de entrega: "al menos una vez". Si el proceso muere justo entre enviar y marcar
`sent`, el aviso puede repetirse al reiniciar, pero jamás se pierde.

Todo lo que depende del tiempo recibe el reloj (`now`) por parámetro.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from asistente.bot.choices import encode_choice_id
from asistente.channels.base import Channel, Choice, PermanentChannelError
from asistente.core.settings import get_time_setting
from asistente.timeutil import (
    Clock,
    from_utc_iso,
    is_quiet_hour,
    local_to_utc,
    to_local,
    to_utc_iso,
)

logger = logging.getLogger(__name__)

# --- Parámetros ----------------------------------------------------------------------------

LATE_GRACE = timedelta(minutes=2)  # más tarde que esto = "(retrasado)"
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 15 * 60
GIVE_UP_AFTER = timedelta(hours=24)  # tiempo total reintentando un canal caído
STOPPED_ATTEMPTS = (
    1000  # valor centinela de `attempts`: el envío se detuvo (ver `Reminder.stopped`)
)

ACTION_DONE = "rem_done"
ACTION_SNOOZE = "rem_snooze"
ACTION_TOMORROW = "rem_tomorrow"
SNOOZE_SHORT_MINUTES = 10
SNOOZE_LONG_MINUTES = 60


def backoff_seconds(attempts: int) -> int:
    """Espera antes del siguiente intento tras `attempts` fallos seguidos (crece y se topa)."""
    return min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_CAP_SECONDS)


def _transient_attempt_limit() -> int:
    """Cuántos fallos seguidos suman las 24 h de reintentos (con la espera creciente)."""
    total = 0
    attempts = 0
    while total < GIVE_UP_AFTER.total_seconds():
        attempts += 1
        total += backoff_seconds(attempts)
    return attempts


TRANSIENT_ATTEMPT_LIMIT = _transient_attempt_limit()


class PastReminderError(ValueError):
    """Se intentó crear un recordatorio en el pasado: jamás se hace, se pregunta al usuario."""


@dataclass(frozen=True)
class Reminder:
    id: int
    task_id: int | None
    text: str
    area_id: int | None
    fire_at_utc: str
    rrule: str | None
    priority: int
    status: str
    snooze_count: int
    attempts: int
    nag_count: int
    created_at: str
    last_fired_at: str | None

    @property
    def stopped(self) -> bool:
        """Envío detenido (error permanente o 24 h sin poder enviar): se marca en /recordatorios."""
        return self.attempts >= STOPPED_ATTEMPTS


def _from_row(row: sqlite3.Row) -> Reminder:
    return Reminder(**{key: row[key] for key in row.keys()})  # noqa: SIM118 (sqlite3.Row)


def get_reminder(conn: sqlite3.Connection, reminder_id: int) -> Reminder | None:
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return _from_row(row) if row else None


# --- Alta y consulta -----------------------------------------------------------------------


def create_reminder(
    conn: sqlite3.Connection,
    text: str,
    fire_at_utc: datetime,
    now: Clock,
    *,
    area_id: int | None = None,
    task_id: int | None = None,
    rrule: str | None = None,
    priority: int = 1,
) -> Reminder:
    """Crea un recordatorio pendiente. Nunca en el pasado (lanza `PastReminderError`)."""
    moment = now()
    if fire_at_utc <= moment:
        raise PastReminderError("No se crean recordatorios en el pasado")
    with conn:
        cursor = conn.execute(
            "INSERT INTO reminders"
            " (task_id, text, area_id, fire_at_utc, rrule, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, text, area_id, to_utc_iso(fire_at_utc), rrule, priority, to_utc_iso(moment)),
        )
    reminder = get_reminder(conn, cursor.lastrowid)
    assert reminder is not None
    return reminder


def list_pending(conn: sqlite3.Connection) -> list[Reminder]:
    """Recordatorios que aún no se han avisado (incluye los detenidos, para marcarlos)."""
    rows = conn.execute("SELECT * FROM reminders WHERE status = 'pending' ORDER BY fire_at_utc, id")
    return [_from_row(row) for row in rows]


def list_due(conn: sqlite3.Connection, moment: datetime) -> list[Reminder]:
    """Pendientes ya vencidos y no detenidos, del más antiguo al más reciente."""
    rows = conn.execute(
        "SELECT * FROM reminders WHERE status = 'pending' AND fire_at_utc <= ? AND attempts < ?"
        " ORDER BY fire_at_utc, id",
        (to_utc_iso(moment), STOPPED_ATTEMPTS),
    )
    return [_from_row(row) for row in rows]


# --- Acciones del usuario (botones) --------------------------------------------------------


def mark_done(conn: sqlite3.Connection, reminder_id: int) -> bool:
    """✅ Hecho. False si ya estaba hecho/cancelado o no existe (botón viejo)."""
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'done' WHERE id = ? AND status IN ('pending', 'sent')",
            (reminder_id,),
        )
    return cursor.rowcount == 1


def cancel(conn: sqlite3.Connection, reminder_id: int) -> bool:
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'cancelled'"
            " WHERE id = ? AND status IN ('pending', 'sent')",
            (reminder_id,),
        )
    return cursor.rowcount == 1


def snooze(
    conn: sqlite3.Connection, reminder_id: int, delta: timedelta, now: Clock
) -> datetime | None:
    """⏱ Reprograma un recordatorio ya avisado: vuelve a `pending` a `now + delta`.

    Devuelve la nueva hora (UTC) o None si el botón ya no aplica (ya hecho, cancelado...).
    """
    return _snooze_to(conn, reminder_id, now() + delta)


def snooze_until_tomorrow(
    conn: sqlite3.Connection, reminder_id: int, now: Clock, tz_name: str
) -> datetime | None:
    """🌅 Mañana a `default_morning_time` (hora local del usuario)."""
    morning = get_time_setting(conn, "default_morning_time")
    tomorrow = to_local(now(), tz_name).date() + timedelta(days=1)
    target = local_to_utc(datetime.combine(tomorrow, morning), tz_name)
    return _snooze_to(conn, reminder_id, target)


def _snooze_to(conn: sqlite3.Connection, reminder_id: int, target: datetime) -> datetime | None:
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'pending', fire_at_utc = ?,"
            " snooze_count = snooze_count + 1, attempts = 0, nag_count = 0"
            " WHERE id = ? AND status = 'sent'",
            (to_utc_iso(target), reminder_id),
        )
    return target if cursor.rowcount == 1 else None


# --- Mensaje -------------------------------------------------------------------------------


def reminder_choices(reminder_id: int) -> list[Choice]:
    return [
        Choice(encode_choice_id(ACTION_DONE, reminder_id), "✅ Hecho"),
        Choice(encode_choice_id(ACTION_SNOOZE, reminder_id, SNOOZE_SHORT_MINUTES), "⏱ +10 min"),
        Choice(encode_choice_id(ACTION_SNOOZE, reminder_id, SNOOZE_LONG_MINUTES), "⏱ +1 h"),
        Choice(encode_choice_id(ACTION_TOMORROW, reminder_id), "🌅 Mañana"),
    ]


def format_reminder_text(text: str, area_name: str | None, delayed: bool) -> str:
    """`⏰ {texto} [{área}]`, con "(retrasado)" si salió tarde."""
    message = f"⏰ {text}"
    if area_name:
        message += f" [{area_name}]"
    if delayed:
        message += " (retrasado)"
    return message


# --- Motor ---------------------------------------------------------------------------------


class ReminderEngine:
    """Revisa y envía los recordatorios vencidos. `tick()` se llama cada 30 s y al arrancar."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        channel: Channel,
        user_ref: str,
        tz_name: str,
        now: Clock,
    ) -> None:
        self._conn = conn
        self._channel = channel
        self._user_ref = user_ref
        self._tz_name = tz_name
        self._now = now
        self._lock = asyncio.Lock()
        # Cuándo reintentar cada recordatorio tras un fallo pasajero. Vive en memoria a propósito:
        # si el proceso se reinicia, se reintenta enseguida (mejor repetir que perder).
        self._retry_at: dict[int, datetime] = {}

    async def tick(self) -> int:
        """Envía lo vencido. Devuelve cuántos mensajes salieron. Nunca se solapa consigo mismo."""
        if self._lock.locked():
            return 0  # el tick anterior sigue en curso (p. ej. Telegram lento): este se salta
        async with self._lock:
            return await self._run_tick()

    async def _run_tick(self) -> int:
        moment = self._now()
        sent = 0
        quiet = self._is_quiet(moment)
        for reminder in list_due(self._conn, moment):
            if quiet and reminder.priority != 2:
                continue  # silencio: se retiene y sale en orden al terminar
            if self._retry_at.get(reminder.id, moment) > moment:
                continue  # en espera tras un fallo pasajero
            if await self._deliver(reminder, moment):
                sent += 1
        return sent

    def _is_quiet(self, moment: datetime) -> bool:
        start = get_time_setting(self._conn, "quiet_start")
        end = get_time_setting(self._conn, "quiet_end")
        return is_quiet_hour(moment, start, end, self._tz_name)

    async def _deliver(self, reminder: Reminder, moment: datetime) -> bool:
        delayed = moment - from_utc_iso(reminder.fire_at_utc) > LATE_GRACE
        text = format_reminder_text(reminder.text, self._area_name(reminder.area_id), delayed)
        try:
            await self._channel.send_choices(
                self._user_ref, text, reminder_choices(reminder.id), kind="reminder"
            )
        except PermanentChannelError as error:
            self._stop(reminder, f"permanente: {error.reason}")
            return False
        except Exception as error:  # noqa: BLE001 - cualquier otro fallo se trata como pasajero
            self._fail_transient(reminder, moment, getattr(error, "reason", type(error).__name__))
            return False
        self._finish_send(reminder, moment)
        return True

    def _area_name(self, area_id: int | None) -> str | None:
        if area_id is None:
            return None
        row = self._conn.execute("SELECT name FROM areas WHERE id = ?", (area_id,)).fetchone()
        return row["name"] if row else None

    def _finish_send(self, reminder: Reminder, moment: datetime) -> None:
        self._retry_at.pop(reminder.id, None)
        with self._conn:
            self._conn.execute(
                "UPDATE reminders SET status = 'sent', last_fired_at = ?, attempts = 0"
                " WHERE id = ?",
                (to_utc_iso(moment), reminder.id),
            )

    def _fail_transient(self, reminder: Reminder, moment: datetime, reason: str) -> None:
        """Fallo pasajero: espera creciente desde `attempts`, sin tocar `fire_at_utc`."""
        attempts = reminder.attempts + 1
        if attempts >= TRANSIENT_ATTEMPT_LIMIT:
            self._stop(reminder, f"se agotaron las 24 h de reintentos ({reason})")
            return
        with self._conn:
            self._conn.execute(
                "UPDATE reminders SET attempts = ? WHERE id = ?", (attempts, reminder.id)
            )
        self._retry_at[reminder.id] = moment + timedelta(seconds=backoff_seconds(attempts))
        logger.warning(
            "Fallo pasajero al enviar recordatorio id=%s intento=%s motivo=%s",
            reminder.id,
            attempts,
            reason,
        )

    def _stop(self, reminder: Reminder, why: str) -> None:
        """Detiene el envío (queda `pending`, `attempts` centinela; se marca en /recordatorios)."""
        self._retry_at.pop(reminder.id, None)
        with self._conn:
            self._conn.execute(
                "UPDATE reminders SET attempts = ? WHERE id = ?", (STOPPED_ATTEMPTS, reminder.id)
            )
        logger.error("Recordatorio id=%s detenido: %s", reminder.id, why)
