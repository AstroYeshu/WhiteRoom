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
from datetime import datetime, time, timedelta
from enum import Enum

from dateutil.rrule import rrulestr

from asistente.bot.choices import encode_choice_id
from asistente.channels.base import (
    Channel,
    Choice,
    PermanentChannelError,
    TransientChannelError,
)
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
MAX_UNEXPECTED_IN_A_ROW = 3  # fallos inesperados seguidos tras los que se corta el tick
BACKOFF_CAP_SECONDS = 5 * 60  # tope de espera entre intentos con el canal caído
RETRY_AFTER_CAP_SECONDS = 10 * 60  # red de seguridad: tope a lo que pide RetryAfter
GIVE_UP_AFTER = timedelta(hours=24)  # horizonte: desde `first_failed_at` (vive en la base)

ACTION_DONE = "rem_done"
ACTION_SNOOZE = "rem_snooze"
ACTION_TOMORROW = "rem_tomorrow"
SNOOZE_SHORT_MINUTES = 10
SNOOZE_LONG_MINUTES = 60
EARLY_MORNING_CUTOFF = time(5, 0)  # antes de esto, "mañana" es hoy (M5)

NAG_INTERVAL = timedelta(minutes=15)  # insistencia (priority=2): cada cuánto se reenvía
NAG_MAX_RESENDS = 3  # reenvíos tras el primer aviso, si no se pulsa ✅ Hecho
PREPARATION_NOTICES = (
    (timedelta(days=1), "Mañana vence"),
    (timedelta(hours=1), "En 1 hora vence"),
)


def backoff_seconds(failures: int) -> int:
    """Espera tras `failures` fallos seguidos del canal (crece y se topa en 5 min)."""
    return min(BACKOFF_BASE_SECONDS * 2 ** max(failures - 1, 0), BACKOFF_CAP_SECONDS)


class Delivery(Enum):
    """Resultado de intentar enviar un recordatorio."""

    SENT = "sent"  # salió y quedó registrado
    SKIPPED = "skipped"  # no salió por esta fila (cambió, se detuvo o falló el registro)
    CHANNEL_DOWN = "channel_down"  # fallo pasajero del canal: se corta el tick
    UNEXPECTED = "unexpected"  # excepción inesperada: ¿falla del canal o de esa fila? (ver el tick)


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
    first_failed_at: str | None
    stopped_at: str | None
    stop_reason: str | None

    @property
    def stopped(self) -> bool:
        """Envío detenido (error permanente o 24 h sin poder enviar): se marca en /recordatorios."""
        return self.stop_reason is not None


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
    with conn:
        reminder_id = _insert_reminder(
            conn, text, fire_at_utc, now, area_id, task_id, rrule, priority
        )
    reminder = get_reminder(conn, reminder_id)
    assert reminder is not None
    return reminder


def _insert_reminder(
    conn: sqlite3.Connection,
    text: str,
    fire_at_utc: datetime,
    now: Clock,
    area_id: int | None,
    task_id: int | None,
    rrule: str | None,
    priority: int,
) -> int:
    """Valida e inserta SIN abrir ni cerrar transacción: la pone quien llama (para poder
    juntar varias escrituras en una sola, p. ej. una tarea y sus avisos)."""
    moment = now()
    if fire_at_utc <= moment:
        raise PastReminderError("No se crean recordatorios en el pasado")
    if rrule is not None:
        rrulestr(rrule, dtstart=fire_at_utc)  # ValueError si la regla no es válida
    cursor = conn.execute(
        "INSERT INTO reminders (task_id, text, area_id, fire_at_utc, rrule, priority, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, text, area_id, to_utc_iso(fire_at_utc), rrule, priority, to_utc_iso(moment)),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


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
        "SELECT * FROM reminders WHERE stop_reason IS NULL AND ("
        " (status = 'pending' AND fire_at_utc <= :now)"
        " OR (status = 'sent' AND priority = 2 AND nag_count < :max_nags"
        "     AND last_fired_at <= :nag_cutoff))"
        " ORDER BY fire_at_utc, id",
        {
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


def reactivate(conn: sqlite3.Connection, reminder_id: int) -> bool:
    """Reactiva un recordatorio detenido (sin UI todavía). False si no estaba detenido.

    Limpia el motivo, los intentos y el horizonte, pero CONSERVA `stopped_at`: es la marca de que
    la serie ya generó su siguiente ocurrencia al detenerse, así que reactivar y enviar no crea otra
    (M13). Si su hora ya pasó sale con "(retrasado)".
    """
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET stop_reason = NULL, attempts = 0, first_failed_at = NULL"
            " WHERE id = ? AND stop_reason IS NOT NULL AND status IN ('pending', 'sent')",
            (reminder_id,),
        )
    return cursor.rowcount == 1


def cancel_for_task(conn: sqlite3.Connection, task_id: int) -> int:
    """Cancela los recordatorios de una tarea que siguen vivos (preparación incluida).

    Vivos = pendientes, o ya avisados con insistencia (`priority=2`) todavía activa. El historial
    (`sent`, `done`) no se toca. Devuelve cuántos canceló.
    """
    with conn:
        return cancel_for_task_in_transaction(conn, task_id)


def cancel_for_task_in_transaction(conn: sqlite3.Connection, task_id: int) -> int:
    """Como `cancel_for_task`, pero dentro de la transacción de quien llama (no hace commit)."""
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
    """Avisos 1 día y 1 hora antes del vencimiento; solo los que todavía no pasaron.

    Los crea todos o ninguno (una transacción).
    """
    with conn:
        ids = insert_preparation_reminders(conn, task_id, title, area_id, due_at_utc, now)
    return [r for r in (get_reminder(conn, i) for i in ids) if r is not None]


def insert_preparation_reminders(
    conn: sqlite3.Connection,
    task_id: int,
    title: str,
    area_id: int | None,
    due_at_utc: datetime,
    now: Clock,
) -> list[int]:
    """Inserta los avisos de preparación dentro de la transacción de quien llama (no hace commit).
    Devuelve los ids creados."""
    created = []
    for offset, label in PREPARATION_NOTICES:
        fire_at = due_at_utc - offset
        if fire_at > now():
            created.append(
                _insert_reminder(conn, f"{label}: {title}", fire_at, now, area_id, task_id, None, 1)
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
    """🌅 Mañana a `default_morning_time` (hora local del usuario).

    Antes de las 05:00 locales "mañana" casi siempre significa "cuando me levante", o sea HOY:
    se ofrece hoy a esa hora, siempre que todavía no haya pasado (M5).
    """
    morning = get_time_setting(conn, "default_morning_time")
    moment = now()
    local_now = to_local(moment, tz_name)
    day = local_now.date()
    if local_now.time() >= EARLY_MORNING_CUTOFF:
        day += timedelta(days=1)
    target = local_to_utc(datetime.combine(day, morning), tz_name)
    if target <= moment:  # la hora de hoy ya pasó: mañana
        target = local_to_utc(datetime.combine(day + timedelta(days=1), morning), tz_name)
    return _snooze_to(conn, reminder_id, target)


def _snooze_to(conn: sqlite3.Connection, reminder_id: int, target: datetime) -> datetime | None:
    with conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'pending', fire_at_utc = ?,"
            " snooze_count = snooze_count + 1, attempts = 0, nag_count = 0, first_failed_at = NULL"
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
        # Backoff a nivel de CANAL (un canal caído lo está para todos). Vive en memoria a propósito:
        # si el proceso se reinicia, se reintenta enseguida (mejor repetir que perder). Lo que NO se
        # reinicia es el horizonte de 24 h, que está en la base (`first_failed_at`).
        self._channel_failures = 0
        self._channel_retry_at: datetime | None = None
        self._last_failure_reason = "unknown"
        self._unexpected_reason = (
            "unknown"  # clase de la última excepción inesperada (solo el tipo)
        )

    async def tick(self) -> int:
        """Envía lo vencido. Devuelve cuántos mensajes salieron. Nunca se solapa consigo mismo."""
        if self._lock.locked():
            return 0  # el tick anterior sigue en curso (p. ej. Telegram lento): este se salta
        async with self._lock:
            return await self._run_tick()

    async def _run_tick(self) -> int:
        moment = self._now()
        if self._channel_retry_at is not None and moment < self._channel_retry_at:
            return 0  # el canal sigue en espera tras un fallo pasajero
        sent = 0
        due = list_due(self._conn, moment)
        # Fallos inesperados a la espera de veredicto: si DESPUÉS sale otro recordatorio, el canal
        # está vivo y la culpa es de esa fila (se aísla); si no, se tratan como pasajeros.
        unexpected: list[tuple[Reminder, str]] = []
        for index, reminder in enumerate(due):
            # El reloj se relee en cada envío (M9): un canal lento no debe falsear el silencio,
            # el "(retrasado)" ni las horas registradas. Solo la consulta usa el instante del tick.
            if self._held_by_silence(reminder):
                continue  # silencio: se retiene y sale en orden al terminar
            result = await self._deliver(reminder)
            if result is Delivery.SENT:
                sent += 1
                for culprit, reason in unexpected:
                    self._stop(culprit, f"permanent:unexpected:{reason}")
                unexpected.clear()
            elif result is Delivery.CHANNEL_DOWN:
                # Corta-circuito: con el canal caído no se intenta ninguno más en este tick.
                self._settle_unexpected(unexpected, channel_counted=True)
                self._flag_blocked(due[index + 1 :])
                return sent
            elif result is Delivery.UNEXPECTED:
                unexpected.append((reminder, self._unexpected_reason))
                if len(unexpected) >= MAX_UNEXPECTED_IN_A_ROW:
                    self._settle_unexpected(unexpected, channel_counted=False)
                    self._flag_blocked(due[index + 1 :])
                    return sent
        self._settle_unexpected(unexpected, channel_counted=False)
        return sent

    def _settle_unexpected(
        self, unexpected: list[tuple[Reminder, str]], channel_counted: bool
    ) -> None:
        """Sin un envío posterior que los absuelva, los fallos inesperados son pasajeros.

        La espera del CANAL se cuenta una sola vez (salvo que `_deliver` ya la contara); cada
        fila anota su propio fallo y su horizonte.
        """
        moment = self._now()
        for culprit, reason in unexpected:
            if channel_counted:
                self._record_row_failure(culprit, moment, reason)
            else:
                self._fail_transient(culprit, moment, reason)
                channel_counted = True
        unexpected.clear()

    def _held_by_silence(self, reminder: Reminder) -> bool:
        return reminder.priority != 2 and self._is_quiet(self._now())

    def _flag_blocked(self, blocked: list[Reminder]) -> None:
        """Los que esperaban turno comparten la caída: empiezan su horizonte ahora (o se detienen
        si ya lo agotaron). Los retenidos por el silencio NO cuentan: no se intentaron enviar."""
        moment = self._now()
        for reminder in blocked:
            if self._held_by_silence(reminder):
                continue
            if reminder.first_failed_at is None:
                with self._conn:
                    self._conn.execute(
                        "UPDATE reminders SET first_failed_at = ? WHERE id = ?",
                        (to_utc_iso(moment), reminder.id),
                    )
            elif moment - from_utc_iso(reminder.first_failed_at) >= GIVE_UP_AFTER:
                self._stop(reminder, self._horizon_reason(self._last_failure_reason))

    def _is_quiet(self, moment: datetime) -> bool:
        start = get_time_setting(self._conn, "quiet_start")
        end = get_time_setting(self._conn, "quiet_end")
        return is_quiet_hour(moment, start, end, self._tz_name)

    async def _deliver(self, reminder: Reminder) -> Delivery:
        # Releer antes de enviar: entre la consulta del tick y este punto el usuario pudo cancelar
        # o posponer. Si la fila cambió, no se envía (el siguiente tick la verá como esté).
        current = get_reminder(self._conn, reminder.id)
        if (
            current is None
            or current.status != reminder.status
            or current.fire_at_utc != reminder.fire_at_utc
        ):
            return Delivery.SKIPPED
        is_resend = reminder.status == "sent"  # insistencia: no es un aviso "retrasado"
        started = self._now()
        delayed = not is_resend and started - from_utc_iso(reminder.fire_at_utc) > LATE_GRACE
        text = format_reminder_text(reminder.text, self._area_name(reminder.area_id), delayed)
        try:
            await self._channel.send_choices(
                self._user_ref, text, reminder_choices(reminder.id), kind="reminder"
            )
        except PermanentChannelError as error:
            self._stop(reminder, f"permanent:{error.reason}")
            return Delivery.SKIPPED  # un fallo permanente es de ESA fila: los demás siguen
        except TransientChannelError as error:
            self._fail_transient(reminder, self._now(), error.reason, error.retry_after)
            return Delivery.CHANNEL_DOWN
        except Exception as error:  # noqa: BLE001 - lo decide el tick (canal caído o fila rota)
            self._unexpected_reason = type(error).__name__  # solo el tipo: nunca el texto
            return Delivery.UNEXPECTED
        self._channel_failures = 0  # el canal respondió: se acabó la espera
        self._channel_retry_at = None
        try:
            return Delivery.SENT if self._finish_send(reminder, self._now()) else Delivery.SKIPPED
        except Exception as error:  # noqa: BLE001 - un fallo de base no debe frenar el resto
            # Todo se revirtió (una sola transacción): en el próximo tick se reintenta entero.
            logger.error(
                "No se pudo registrar el envío del recordatorio id=%s: %s",
                reminder.id,
                type(error).__name__,
            )
            return Delivery.SKIPPED

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
        pisa su acción: sin siguiente de serie y sin insistencia. Un reenvío de insistencia solo
        toca la fila si sigue en `sent` (M10). Devuelve si se registró.
        """
        if reminder.status == "sent":  # reenvío de insistencia
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE reminders SET nag_count = nag_count + 1, last_fired_at = ?,"
                    " attempts = 0, first_failed_at = NULL WHERE id = ? AND status = 'sent'",
                    (to_utc_iso(moment), reminder.id),
                )
            if cursor.rowcount != 1:  # ✅ Hecho, cancelado o pospuesto mientras se reenviaba
                return False
        else:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE reminders SET status = 'sent', last_fired_at = ?, attempts = 0,"
                    " first_failed_at = NULL"
                    " WHERE id = ? AND status = 'pending' AND fire_at_utc = ?",
                    (to_utc_iso(moment), reminder.id, reminder.fire_at_utc),
                )
                if cursor.rowcount != 1:
                    return False
                self._spawn_next(reminder, moment)
        return True

    def _spawn_next(self, reminder: Reminder, moment: datetime) -> None:
        """Inserta la siguiente ocurrencia de una serie, contada desde la hora PROGRAMADA.

        Solo en el primer disparo de la fila (`last_fired_at` vacío): una fila pospuesta o
        reenviada ya generó su siguiente y no crea otra. Tras una caída larga se salta a la
        primera ocurrencia posterior a `now`, sin ráfaga de las que se perdieron.
        """
        if reminder.rrule is None or reminder.last_fired_at is not None:
            return
        if reminder.stopped_at is not None:
            return  # ya se detuvo antes (y creó su siguiente): reactivarla no crea otra (M13)
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

    @staticmethod
    def _horizon_reason(reason: str) -> str:
        return f"horizon:{reason}"

    def _fail_transient(
        self,
        reminder: Reminder,
        moment: datetime,
        reason: str,
        retry_after: float | None = None,
    ) -> None:
        """Fallo pasajero: el CANAL espera más cada vez (con tope); la fila lleva su horizonte.

        Si la plataforma pidió una espera (`retry_after`), se espera AL MENOS eso, con un tope de
        10 min como red de seguridad. No toca `fire_at_utc`. Si el primer fallo de la fila fue hace
        24 h o más, se detiene.
        """
        self._last_failure_reason = reason
        self._channel_failures += 1
        wait = backoff_seconds(self._channel_failures)
        if retry_after is not None:
            wait = max(wait, min(retry_after, RETRY_AFTER_CAP_SECONDS))
        self._channel_retry_at = moment + timedelta(seconds=wait)
        self._record_row_failure(reminder, moment, reason)

    def _record_row_failure(self, reminder: Reminder, moment: datetime, reason: str) -> None:
        """Anota el fallo en la FILA (intentos y horizonte); no cambia la espera del canal."""
        self._last_failure_reason = reason
        first_failed = (
            from_utc_iso(reminder.first_failed_at) if reminder.first_failed_at else moment
        )
        if moment - first_failed >= GIVE_UP_AFTER:
            self._stop(reminder, self._horizon_reason(reason))
            return
        with self._conn:
            self._conn.execute(
                "UPDATE reminders SET attempts = ?, first_failed_at = ? WHERE id = ?",
                (reminder.attempts + 1, to_utc_iso(first_failed), reminder.id),
            )
        logger.warning(
            "Fallo pasajero al enviar recordatorio id=%s intento=%s motivo=%s",
            reminder.id,
            reminder.attempts + 1,
            reason,
        )

    def _stop(self, reminder: Reminder, why: str) -> None:
        """Detiene el envío (queda `pending` con `stop_reason`; se marca en /recordatorios).

        `why` es un código estable (`permanent:<motivo>` / `horizon:<motivo>`), no prosa: el texto
        para el usuario lo pone la interfaz. Si es una serie, la siguiente ocurrencia se crea igual
        (rendirse con una no corta la serie), en la MISMA transacción: `stopped_at` no nulo
        significa "ya se generó la siguiente". Si algo falla, no queda detenido a medias y el tick
        sigue.
        """
        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE reminders SET stopped_at = ?, stop_reason = ? WHERE id = ?",
                    (to_utc_iso(self._now()), why, reminder.id),
                )
                if reminder.status == "pending":
                    self._spawn_next(reminder, self._now())
        except Exception as error:  # noqa: BLE001 - un fallo de base no debe frenar el resto
            logger.error(
                "No se pudo detener el recordatorio id=%s: %s", reminder.id, type(error).__name__
            )
            return
        logger.error("Recordatorio id=%s detenido: %s", reminder.id, why)
