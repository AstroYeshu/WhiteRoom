"""Motor de recordatorios (base): envío único, +10 min, silencio, reintentos y no solapamiento.

Todo con reloj falso, canal falso y SQLite en memoria con las migraciones reales.
Reloj inicial: sábado 2026-10-03 15:30 en México (21:30 UTC). Silencio: 22:00-07:00.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from asistente.channels.base import PermanentChannelError, TransientChannelError
from asistente.core import areas, reminders
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import local_to_utc, to_utc_iso
from tests.fakes import FakeChannel, ScriptedChannel

TZ = "America/Mexico_City"
USER = "42"


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


@pytest.fixture
def channel() -> ScriptedChannel:
    return ScriptedChannel()


@pytest.fixture
def engine(conn, channel, clock) -> ReminderEngine:
    return ReminderEngine(conn, channel, USER, TZ, clock)


def tick(engine: ReminderEngine) -> int:
    return asyncio.run(engine.tick())


def row(conn, reminder_id: int):
    return reminders.get_reminder(conn, reminder_id)


def sent_texts(channel: FakeChannel) -> list[str]:
    return [text for _, text, _, _ in channel.choices]


# --- 1. Recordatorio único ------------------------------------------------------------------


def test_unico_dispara_a_su_hora_una_sola_vez(conn, clock, engine, channel):
    due = clock() + timedelta(minutes=10)
    created = reminders.create_reminder(conn, "llevar tarea de cálculo", due, clock)

    clock.advance(minutes=9, seconds=59)
    assert tick(engine) == 0 and not channel.sent_anything

    clock.advance(seconds=1)  # exactamente a su hora
    assert tick(engine) == 1
    to, text, choices, kind = channel.choices[0]
    assert (to, text, kind) == (USER, "⏰ llevar tarea de cálculo", "reminder")
    assert [c.label for c in choices] == ["✅ Hecho", "⏱ +10 min", "⏱ +1 h", "🌅 Mañana"]
    assert [c.id for c in choices] == [
        f"rem_done:{created.id}",
        f"rem_snooze:{created.id}:10",
        f"rem_snooze:{created.id}:60",
        f"rem_tomorrow:{created.id}",
    ]
    stored = row(conn, created.id)
    assert stored.status == "sent" and stored.last_fired_at == to_utc_iso(clock())

    clock.advance(minutes=5)
    assert tick(engine) == 0  # no se repite
    assert len(channel.choices) == 1


def test_el_mensaje_lleva_el_area(conn, clock, engine, channel):
    uni = areas.find_area_by_name(conn, "universidad")
    reminders.create_reminder(
        conn, "estudiar", clock() + timedelta(minutes=1), clock, area_id=uni.id
    )
    clock.advance(minutes=1)
    tick(engine)
    assert sent_texts(channel) == ["⏰ estudiar [universidad]"]


def test_un_retraso_pequeno_no_se_etiqueta(conn, clock, engine, channel):
    reminders.create_reminder(conn, "a", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1, seconds=30)  # un tick de 30 s llegó tarde, dentro de la gracia
    tick(engine)
    assert sent_texts(channel) == ["⏰ a"]


# --- 2. +10 min / +1 h / mañana -------------------------------------------------------------


def test_posponer_10_minutos_reprograma_y_vuelve_a_sonar(conn, clock, engine, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    tick(engine)

    new_time = reminders.snooze(conn, created.id, timedelta(minutes=10), clock)
    assert new_time == clock() + timedelta(minutes=10)
    stored = row(conn, created.id)
    assert (stored.status, stored.snooze_count) == ("pending", 1)
    assert stored.fire_at_utc == to_utc_iso(new_time)

    clock.advance(minutes=9, seconds=59)
    assert tick(engine) == 0
    clock.advance(seconds=1)
    assert tick(engine) == 1
    assert sent_texts(channel) == ["⏰ x", "⏰ x"]  # el segundo salió a su hora: sin "(retrasado)"


def test_posponer_1_hora(conn, clock, engine, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    tick(engine)
    assert reminders.snooze(conn, created.id, timedelta(hours=1), clock) == clock() + timedelta(
        hours=1
    )
    clock.advance(minutes=59)
    assert tick(engine) == 0
    clock.advance(minutes=1)
    assert tick(engine) == 1


def test_manana_va_a_la_hora_por_defecto_en_hora_local(conn, clock, engine):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    tick(engine)
    target = reminders.snooze_until_tomorrow(conn, created.id, clock, TZ)
    assert target == local("2026-10-04 09:00")  # default_morning_time = 09:00


def test_botones_viejos_no_hacen_nada(conn, clock, engine):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    # Aún no se ha avisado: no hay botón que pulsar, posponer no aplica.
    assert reminders.snooze(conn, created.id, timedelta(minutes=10), clock) is None
    clock.advance(minutes=1)
    tick(engine)
    assert reminders.mark_done(conn, created.id) is True
    assert reminders.mark_done(conn, created.id) is False  # ya estaba hecho
    assert reminders.snooze(conn, created.id, timedelta(minutes=10), clock) is None
    assert reminders.snooze_until_tomorrow(conn, created.id, clock, TZ) is None
    assert row(conn, created.id).status == "done"
    assert reminders.snooze(conn, 999, timedelta(minutes=10), clock) is None


def test_hecho_o_cancelado_no_vuelve_a_sonar(conn, clock, engine, channel):
    done = reminders.create_reminder(conn, "hecho", clock() + timedelta(minutes=1), clock)
    cancelled = reminders.create_reminder(conn, "cancelado", clock() + timedelta(minutes=1), clock)
    assert reminders.mark_done(conn, done.id) is True  # se marca antes de que suene
    assert reminders.cancel(conn, cancelled.id) is True
    clock.advance(minutes=5)
    assert tick(engine) == 0
    assert not channel.sent_anything


# --- 4. Silencio ----------------------------------------------------------------------------


def test_silencio_retiene_y_libera_en_orden_con_retrasado(conn, clock, engine, channel):
    clock.current = local("2026-10-03 21:30")
    first = reminders.create_reminder(conn, "primero", local("2026-10-03 22:10"), clock)
    second = reminders.create_reminder(conn, "segundo", local("2026-10-03 22:40"), clock)
    urgent = reminders.create_reminder(
        conn, "urgente", local("2026-10-03 22:50"), clock, priority=2
    )

    clock.current = local("2026-10-03 22:50")
    clock.advance(seconds=30)
    assert tick(engine) == 1  # solo el prioritario atraviesa el silencio
    assert sent_texts(channel) == ["⏰ urgente"]
    assert row(conn, first.id).status == row(conn, second.id).status == "pending"
    assert reminders.mark_done(conn, urgent.id)  # ✅ Hecho: sin esto insistiría cada 15 min

    clock.current = local("2026-10-04 06:59")
    assert tick(engine) == 0  # sigue en silencio
    clock.current = local("2026-10-04 07:00")  # el fin del silencio es exclusivo
    assert tick(engine) == 2
    assert sent_texts(channel)[1:] == ["⏰ primero (retrasado)", "⏰ segundo (retrasado)"]
    assert row(conn, urgent.id).status == "done"


# --- 6. Fallos de envío: canal caído, permanentes, 24 h -------------------------------------


def test_backoff_crece_y_se_topa():
    assert [reminders.backoff_seconds(n) for n in range(1, 8)] == [30, 60, 120, 240, 480, 900, 900]


def test_el_limite_transitorio_equivale_a_24_horas():
    total = lambda n: sum(reminders.backoff_seconds(i) for i in range(1, n + 1))  # noqa: E731
    day = 24 * 3600
    assert total(reminders.TRANSIENT_ATTEMPT_LIMIT) >= day
    assert total(reminders.TRANSIENT_ATTEMPT_LIMIT - 1) < day


def test_canal_caido_10_minutos_no_pierde_ninguno_y_salen_retrasados(conn, clock, engine, channel):
    start = clock()
    ids = [
        reminders.create_reminder(conn, f"r{i}", start + timedelta(minutes=i + 1), clock).id
        for i in range(3)
    ]
    channel.always_fail_with(TransientChannelError("timeout"))

    while clock() < start + timedelta(minutes=10):  # un tick cada 30 s durante la caída
        tick(engine)
        for reminder_id in ids:  # fire_at no se toca nunca
            assert row(conn, reminder_id).fire_at_utc == to_utc_iso(
                start + timedelta(minutes=ids.index(reminder_id) + 1)
            )
        clock.advance(seconds=30)
    assert not channel.sent_anything
    assert all(row(conn, i).status == "pending" and row(conn, i).attempts >= 1 for i in ids)

    channel.always_fail_with(None)  # vuelve la red
    for _ in range(40):  # hasta 20 min de ticks: el tope de espera es de 15 min
        tick(engine)
        clock.advance(seconds=30)
    assert sorted(sent_texts(channel)) == [
        "⏰ r0 (retrasado)",
        "⏰ r1 (retrasado)",
        "⏰ r2 (retrasado)",
    ]
    assert all(row(conn, i).status == "sent" and row(conn, i).attempts == 0 for i in ids)


def test_tras_un_fallo_espera_antes_de_reintentar(conn, clock, engine, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    channel.always_fail_with(TransientChannelError("timeout"))
    tick(engine)
    assert row(conn, created.id).attempts == 1
    clock.advance(seconds=29)
    tick(engine)
    assert len(channel.attempts) == 1  # aún en espera (30 s)
    clock.advance(seconds=1)
    tick(engine)
    assert len(channel.attempts) == 2 and row(conn, created.id).attempts == 2
    clock.advance(seconds=59)
    tick(engine)
    assert len(channel.attempts) == 2  # ahora la espera es de 60 s


def test_un_error_desconocido_se_trata_como_pasajero(conn, clock, engine, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    channel.always_fail_with(RuntimeError("algo raro"))
    tick(engine)
    stored = row(conn, created.id)
    assert (stored.status, stored.attempts, stored.stopped) == ("pending", 1, False)


def test_error_permanente_detiene_ese_recordatorio_y_los_demas_siguen(conn, clock, engine, channel):
    bad = reminders.create_reminder(conn, "malo", clock() + timedelta(minutes=1), clock)
    good = reminders.create_reminder(conn, "bueno", clock() + timedelta(minutes=1), clock)
    channel.fail_if = lambda text: PermanentChannelError("bot_blocked") if "malo" in text else None
    clock.advance(minutes=1)
    assert tick(engine) == 1
    assert sent_texts(channel) == ["⏰ bueno"]
    assert row(conn, good.id).status == "sent"
    stopped = row(conn, bad.id)
    assert stopped.status == "pending" and stopped.stopped is True  # marcado, no perdido
    assert [r.id for r in reminders.list_pending(conn) if r.stopped] == [bad.id]

    clock.advance(hours=3)
    tick(engine)
    assert channel.attempts.count("⏰ malo (retrasado)") + channel.attempts.count("⏰ malo") == 1


def test_tras_24_horas_de_canal_caido_se_detiene(conn, clock, engine, channel):
    start = clock()
    # Prioridad 2: el silencio nocturno no la retiene, así los ticks no se saltan durante las 24 h.
    created = reminders.create_reminder(conn, "x", start + timedelta(minutes=1), clock, priority=2)
    channel.always_fail_with(TransientChannelError("telegram_down"))
    clock.advance(minutes=1)
    for _ in range(reminders.TRANSIENT_ATTEMPT_LIMIT - 1):
        tick(engine)
        clock.advance(seconds=reminders.BACKOFF_CAP_SECONDS)
        assert row(conn, created.id).stopped is False
    tick(engine)
    assert row(conn, created.id).stopped is True
    assert clock() - start >= timedelta(hours=24)


def test_reiniciar_el_proceso_reintenta_de_inmediato(conn, clock, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    channel.always_fail_with(TransientChannelError("timeout"))
    first_run = ReminderEngine(conn, channel, USER, TZ, clock)
    asyncio.run(first_run.tick())
    channel.always_fail_with(None)
    second_run = ReminderEngine(conn, channel, USER, TZ, clock)  # el "arranque tras una caída"
    assert asyncio.run(second_run.tick()) == 1
    assert row(conn, created.id).status == "sent"


def test_el_log_de_un_fallo_no_incluye_el_texto_del_recordatorio(
    conn, clock, engine, channel, caplog
):
    reminders.create_reminder(conn, "secreto-médico", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    channel.always_fail_with(TransientChannelError("timeout"))
    with caplog.at_level(logging.INFO):
        tick(engine)
    assert caplog.records
    assert "secreto-médico" not in caplog.text


# --- 12. Nunca en el pasado -----------------------------------------------------------------


@pytest.mark.parametrize("delta", [timedelta(seconds=-1), timedelta(0), timedelta(days=-3)])
def test_no_se_crean_recordatorios_en_el_pasado(conn, clock, delta):
    with pytest.raises(reminders.PastReminderError):
        reminders.create_reminder(conn, "x", clock() + delta, clock)
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


# --- 13. Sin solapamiento -------------------------------------------------------------------


def test_un_tick_no_se_solapa_con_el_anterior(conn, clock):
    reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)

    class SlowChannel(FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def send_choices(self, to, text, choices, kind="reply"):
            self.calls += 1
            self.entered.set()
            await self.release.wait()  # Telegram lento
            await super().send_choices(to, text, choices, kind)

    async def scenario() -> tuple[int, int, int]:
        slow = SlowChannel()
        engine = ReminderEngine(conn, slow, USER, TZ, clock)
        first = asyncio.create_task(engine.tick())
        await slow.entered.wait()
        overlapping = await engine.tick()  # entra mientras el primero sigue enviando
        slow.release.set()
        return await first, overlapping, slow.calls

    sent_first, sent_overlapping, calls = asyncio.run(scenario())
    assert (sent_first, sent_overlapping, calls) == (1, 0, 1)  # un solo envío, no dos


def test_un_tick_puede_correr_despues_de_que_termina_el_anterior(conn, clock, engine):
    reminders.create_reminder(conn, "a", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    assert tick(engine) == 1
    reminders.create_reminder(conn, "b", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    assert tick(engine) == 1


def test_utc_es_la_zona_de_almacenamiento(conn, clock):
    created = reminders.create_reminder(conn, "x", datetime(2026, 10, 5, 15, 0, tzinfo=UTC), clock)
    assert created.fire_at_utc == "2026-10-05T15:00:00+00:00"
