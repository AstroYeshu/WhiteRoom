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

from dateutil.rrule import rrulestr

from asistente.bot.choices import encode_choice_id
from asistente.channels.base import Channel, Choice, PermanentChannelError
from asistente.core.settings import get_time_setting
from asistente.parsing.recurrence import next_occurrence
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

NAG_INTERVAL = timedelta(minutes=15)  # insistencia (priority=2): cada cuánto se reenvía
NAG_MAX_RESENDS = 3  # reenvíos tras el primer aviso, si no se pulsa ✅ Hecho
PREPARATION_NOTICES = (
    (timedelta(days=1), "Mañana vence"),
    (timedelta(hours=1), "En 1 hora vence"),
)


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
    if rrule is not None:
        rrulestr(rrule, dtstart=fire_at_utc)  # ValueError si la regla no es válida
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
    """Lo que toca enviar ahora, del más antiguo al más reciente, sin los detenidos.

    - Pendientes cuya hora ya llegó (incluye los vencidos por una caída).
    - Reenvíos de insistencia: `priority=2` ya avisado, sin ✅ Hecho, con menos de
      `NAG_MAX_RESENDS` reenvíos y al menos `NAG_INTERVAL` desde el último aviso.
    """
    rows = conn.execute(
        "SELECT * FROM reminders WHERE attempts < :stopped AND ("
        " (status = 'pending' AND fire_at_utc <= :now)"
        " OR (status = 'sent' AND priority = 2 AND nag_count < :max_nags"
        "     AND last_fired_at <= :nag_cutoff))"
        " ORDER BY fire_at_utc, id",
        {
            "stopped": STOPPED_ATTEMPTS,
            "now": to_utc_iso(moment),
            "max_nags": NAG_MAX_RESENDS,
            "nag_cutoff": to_utc_iso(moment - NAG_INTERVAL),
        },
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


def cancel_for_task(conn: sqlite3.Connection, task_id: int) -> int:
    """Cancela los recordatorios de una tarea que siguen vivos (preparación incluida).

    Vivos = pendientes, o ya avisados con insistencia (`priority=2`) todavía activa. El historial
    (`sent`, `done`) no se toca. Devuelve cuántos canceló.
    """
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE task_id = ? AND ("
            " status = 'pending' OR (status = 'sent' AND priority = 2 AND nag_count < ?))",
            (task_id, NAG_MAX_RESENDS),
        )
    return cursor.rowcount


def create_preparation_reminders(
    conn: sqlite3.Connection,
    task_id: int,
    title: str,
    area_id: int | None,
    due_at_utc: datetime,
    now: Clock,
) -> list[Reminder]:
    """Avisos 1 día y 1 hora antes del vencimiento; solo los que todavía no pasaron."""
    created = []
    for offset, label in PREPARATION_NOTICES:
        fire_at = due_at_utc - offset
        if fire_at > now():
            created.append(
                create_reminder(
                    conn, f"{label}: {title}", fire_at, now, area_id=area_id, task_id=task_id
                )
            )
    return created


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
        # Releer antes de enviar: entre la consulta del tick y este punto el usuario pudo cancelar
        # o posponer. Si la fila cambió, no se envía (el siguiente tick la verá como esté).
        current = get_reminder(self._conn, reminder.id)
        if (
            current is None
            or current.status != reminder.status
            or current.fire_at_utc != reminder.fire_at_utc
        ):
            self._retry_at.pop(reminder.id, None)
            return False
        is_resend = reminder.status == "sent"  # insistencia: no es un aviso "retrasado"
        delayed = not is_resend and moment - from_utc_iso(reminder.fire_at_utc) > LATE_GRACE
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
        try:
            return self._finish_send(reminder, moment)
        except Exception as error:  # noqa: BLE001 - un fallo de base no debe frenar el resto
            # Todo se revirtió (una sola transacción): en el próximo tick se reintenta entero.
            logger.error(
                "No se pudo registrar el envío del recordatorio id=%s: %s",
                reminder.id,
                type(error).__name__,
            )
            return False

    def _area_name(self, area_id: int | None) -> str | None:
        if area_id is None:
            return None
        row = self._conn.execute("SELECT name FROM areas WHERE id = ?", (area_id,)).fetchone()
        return row["name"] if row else None

    def _finish_send(self, reminder: Reminder, moment: datetime) -> bool:
        """Registra el envío. En el primer aviso de una serie, marcar `sent` e insertar la
        siguiente ocurrencia es UNA transacción: o ocurren las dos cosas o ninguna.

        Solo marca `sent` si la fila sigue `pending` en la MISMA hora que se leyó antes de enviar
        (comprueba filas afectadas). Si el usuario canceló o pospuso mientras se enviaba, no se
        pisa su acción: sin siguiente de serie y sin insistencia. Devuelve si se registró.
        """
        if reminder.status == "sent":  # reenvío de insistencia
            with self._conn:
                self._conn.execute(
                    "UPDATE reminders SET nag_count = nag_count + 1, last_fired_at = ?,"
                    " attempts = 0 WHERE id = ?",
                    (to_utc_iso(moment), reminder.id),
                )
        else:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE reminders SET status = 'sent', last_fired_at = ?, attempts = 0"
                    " WHERE id = ? AND status = 'pending' AND fire_at_utc = ?",
                    (to_utc_iso(moment), reminder.id, reminder.fire_at_utc),
                )
                if cursor.rowcount != 1:
                    return False
                self._spawn_next(reminder, moment)
        self._retry_at.pop(reminder.id, None)
        return True

    def _spawn_next(self, reminder: Reminder, moment: datetime) -> None:
        """Inserta la siguiente ocurrencia de una serie, contada desde la hora PROGRAMADA.

        Solo en el primer disparo de la fila (`last_fired_at` vacío): una fila pospuesta o
        reenviada ya generó su siguiente y no crea otra. Tras una caída larga se salta a la
        primera ocurrencia posterior a `now`, sin ráfaga de las que se perdieron.
        """
        if reminder.rrule is None or reminder.last_fired_at is not None:
            return
        scheduled = from_utc_iso(reminder.fire_at_utc)
        following = next_occurrence(
            reminder.rrule, scheduled, max(scheduled, moment), self._tz_name
        )
        if following is None:
            return  # la serie terminó (COUNT/UNTIL)
        self._conn.execute(
            "INSERT INTO reminders"
            " (task_id, text, area_id, fire_at_utc, rrule, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                reminder.task_id,
                reminder.text,
                reminder.area_id,
                to_utc_iso(following),
                reminder.rrule,
                reminder.priority,
                to_utc_iso(moment),
            ),
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
        """Detiene el envío (queda `pending`, `attempts` centinela; se marca en /recordatorios).

        Si es una serie, la siguiente ocurrencia se crea igual: rendirse con una no corta la serie.
        """
        self._retry_at.pop(reminder.id, None)
        with self._conn:
            self._conn.execute(
                "UPDATE reminders SET attempts = ? WHERE id = ?", (STOPPED_ATTEMPTS, reminder.id)
            )
            if reminder.status == "pending":
                self._spawn_next(reminder, self._now())
        logger.error("Recordatorio id=%s detenido: %s", reminder.id, why)
