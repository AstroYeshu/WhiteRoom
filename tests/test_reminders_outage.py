"""Canal caído (M3/M6): horizonte de 24 h en la base, espera con tope de 5 min, backoff por canal
con corta-circuito, silencio que no gasta horizonte y reactivación de detenidos.

Reloj inicial: sábado 2026-10-03 15:30 en México (21:30 UTC). Silencio: 22:00-07:00.
"""

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timedelta

import pytest

from asistente.channels.base import PermanentChannelError, TransientChannelError
from asistente.core import reminders
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import from_utc_iso, local_to_utc, to_utc_iso
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"
USER = "42"
DOWN = TransientChannelError("telegram_down")


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


@pytest.fixture
def channel() -> ScriptedChannel:
    return ScriptedChannel()


@pytest.fixture
def engine(conn, channel, clock) -> ReminderEngine:
    return ReminderEngine(conn, channel, USER, TZ, clock)


# Un solo bucle de asyncio para TODAS las pruebas del módulo. Crear uno por prueba (`asyncio.run`)
# a veces se colgaba en Windows dentro de `_fallback_socketpair` (socket interno del bucle).
_runner: asyncio.Runner | None = None


@pytest.fixture(scope="module", autouse=True)
def _module_loop():
    global _runner
    with asyncio.Runner() as runner:
        _runner = runner
        yield runner
    _runner = None


def run(coroutine: Coroutine):
    assert _runner is not None, "falta el fixture _module_loop"
    return _runner.run(coroutine)


def tick(engine: ReminderEngine) -> int:
    return run(engine.tick())


def row(conn, reminder_id: int):
    return reminders.get_reminder(conn, reminder_id)


def all_rows(conn) -> list[reminders.Reminder]:
    return [row(conn, r["id"]) for r in conn.execute("SELECT id FROM reminders ORDER BY id")]


# --- Horizonte de 24 h ----------------------------------------------------------------------


def test_se_detiene_a_las_24_horas_del_primer_fallo(conn, clock, engine, channel):
    # Prioridad 2: el silencio nocturno no salta ticks durante las 24 h.
    created = reminders.create_reminder(
        conn, "x", clock() + timedelta(minutes=1), clock, priority=2
    )
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    first_failure = clock()

    stopped_at = None
    while clock() < first_failure + timedelta(hours=24, minutes=10):
        tick(engine)
        if row(conn, created.id).stopped:
            stopped_at = clock()
            break
        clock.advance(seconds=30)

    assert row(conn, created.id).first_failed_at == to_utc_iso(first_failure)
    assert stopped_at is not None
    elapsed = stopped_at - first_failure
    assert timedelta(hours=24) <= elapsed <= timedelta(hours=24, seconds=330)  # un tope de espera
    stored = row(conn, created.id)
    assert stored.stop_reason == "horizon:telegram_down"  # código estable, no prosa
    assert from_utc_iso(stored.stopped_at) == stopped_at


def test_reiniciar_el_proceso_no_reinicia_el_horizonte(conn, clock, channel):
    created = reminders.create_reminder(
        conn, "x", clock() + timedelta(minutes=1), clock, priority=2
    )
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    run(ReminderEngine(conn, channel, USER, TZ, clock).tick())  # primer fallo
    first_failure = clock()

    clock.current = first_failure + timedelta(hours=23, minutes=59)
    run(ReminderEngine(conn, channel, USER, TZ, clock).tick())  # proceso nuevo
    assert row(conn, created.id).stopped is False
    assert row(conn, created.id).first_failed_at == to_utc_iso(first_failure)  # intacto

    clock.current = first_failure + timedelta(hours=24, minutes=1)
    run(ReminderEngine(conn, channel, USER, TZ, clock).tick())  # otro proceso nuevo
    assert row(conn, created.id).stopped is True


def test_el_exito_y_el_posponer_borran_el_horizonte(conn, clock, engine, channel):
    ok = reminders.create_reminder(conn, "ok", clock() + timedelta(minutes=1), clock)
    nag = reminders.create_reminder(conn, "nag", clock() + timedelta(minutes=1), clock, priority=2)
    clock.advance(minutes=1)
    tick(engine)  # ambos salen
    assert row(conn, nag.id).status == "sent"

    channel.always_fail_with(DOWN)
    clock.advance(minutes=15)
    tick(engine)  # el reenvío de la insistencia falla
    assert row(conn, nag.id).first_failed_at is not None
    assert reminders.snooze(conn, nag.id, timedelta(minutes=10), clock) is not None
    assert row(conn, nag.id).first_failed_at is None  # posponer lo borra
    assert row(conn, ok.id).first_failed_at is None

    again = reminders.create_reminder(conn, "otra", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    tick(engine)
    assert row(conn, again.id).first_failed_at is not None
    channel.always_fail_with(None)
    clock.advance(minutes=6)
    assert tick(engine) >= 1
    assert row(conn, again.id).status == "sent" and row(conn, again.id).first_failed_at is None


# --- Backoff a nivel de canal con corta-circuito ----------------------------------------------


def test_al_primer_fallo_pasajero_no_se_intentan_los_demas(conn, clock, engine, channel):
    ids = [
        reminders.create_reminder(conn, f"r{i}", clock() + timedelta(minutes=1), clock).id
        for i in range(3)
    ]
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    start = clock()
    assert tick(engine) == 0
    assert len(channel.attempts) == 1  # corta-circuito: solo el primero
    assert [row(conn, i).first_failed_at for i in ids] == [to_utc_iso(start)] * 3  # todos esperan


def test_la_espera_es_del_canal_no_de_cada_recordatorio(conn, clock, engine, channel):
    first = reminders.create_reminder(conn, "a", clock() + timedelta(minutes=1), clock)
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    tick(engine)
    second = reminders.create_reminder(conn, "b", clock() + timedelta(seconds=5), clock)
    clock.advance(seconds=29)
    tick(engine)
    assert len(channel.attempts) == 1  # el canal sigue en espera (30 s), aunque b es nuevo
    clock.advance(seconds=1)
    tick(engine)
    assert len(channel.attempts) == 2  # un solo intento más: el de a
    assert row(conn, first.id).attempts == 2 and row(conn, second.id).attempts == 0
    clock.advance(seconds=59)
    tick(engine)
    assert len(channel.attempts) == 2  # la espera del canal creció a 60 s


def test_la_espera_del_canal_se_topa_en_5_minutos(conn, clock, engine, channel):
    reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock, priority=2)
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    times: list[datetime] = []
    for _ in range(60):  # 30 min de ticks cada 30 s
        before = len(channel.attempts)
        tick(engine)
        if len(channel.attempts) > before:
            times.append(clock())
        clock.advance(seconds=30)
    gaps = [int((b - a).total_seconds()) for a, b in zip(times, times[1:], strict=False)]
    assert gaps[:5] == [30, 60, 120, 240, 300]
    assert set(gaps[4:]) == {300}


def test_un_fallo_permanente_no_corta_a_los_demas(conn, clock, engine, channel):
    bad = reminders.create_reminder(conn, "malo", clock() + timedelta(minutes=1), clock)
    good = reminders.create_reminder(conn, "bueno", clock() + timedelta(minutes=1), clock)
    channel.fail_if = lambda text: (
        PermanentChannelError("chat_not_found") if "malo" in text else None
    )
    clock.advance(minutes=1)
    assert tick(engine) == 1
    assert row(conn, bad.id).stopped and row(conn, good.id).status == "sent"


# --- Silencio: la prioridad 1 retenida no gasta horizonte -------------------------------------


def test_prioridad_1_retenida_por_el_silencio_no_consume_el_horizonte(conn, clock, engine, channel):
    clock.current = local("2026-10-03 21:30")
    urgent = reminders.create_reminder(conn, "p2", local("2026-10-03 22:05"), clock, priority=2)
    normal = reminders.create_reminder(conn, "p1", local("2026-10-03 22:10"), clock)
    channel.always_fail_with(DOWN)

    clock.current = local("2026-10-03 22:05")
    while clock() < local("2026-10-04 06:59"):  # toda la noche con el canal caído
        tick(engine)
        clock.advance(seconds=30)
    assert row(conn, urgent.id).first_failed_at is not None  # la urgente sí lo gasta
    held = row(conn, normal.id)
    assert (held.first_failed_at, held.attempts) == (None, 0)  # la retenida no
    assert all("p2" in text for text in channel.attempts)  # nunca se intentó enviar p1

    channel.always_fail_with(None)  # vuelve el canal y termina el silencio
    clock.current = local("2026-10-04 07:00")
    for _ in range(12):
        tick(engine)
        clock.advance(seconds=30)
    assert row(conn, normal.id).status == "sent"
    assert "<b>p1</b>\n\nRecordatorio <i>(retrasado)</i>" in [
        text for _, text, _, _ in channel.choices
    ]
    assert row(conn, normal.id).first_failed_at is None


# --- Detenidos: log y reactivación ------------------------------------------------------------


def test_un_detenido_registra_el_tipo_de_error_y_nunca_el_texto(
    conn, clock, engine, channel, caplog
):
    reminders.create_reminder(conn, "secreto-médico", clock() + timedelta(minutes=1), clock)
    channel.always_fail_with(PermanentChannelError("bot_blocked"))
    clock.advance(minutes=1)
    with caplog.at_level(logging.INFO):
        tick(engine)
    assert "bot_blocked" in caplog.text
    assert "secreto-médico" not in caplog.text


def test_un_error_desconocido_registra_su_clase_al_detenerse(conn, clock, engine, channel, caplog):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    channel.always_fail_with(RuntimeError("secreto-médico"))
    clock.advance(minutes=1)
    tick(engine)
    clock.advance(hours=24, minutes=10)
    with caplog.at_level(logging.INFO):
        tick(engine)
    assert row(conn, created.id).stopped
    assert "RuntimeError" in caplog.text
    assert "secreto-médico" not in caplog.text


def test_reactivar_un_detenido_lo_envia_retrasado(conn, clock, engine, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    channel.always_fail_with(PermanentChannelError("bot_blocked"))
    clock.advance(minutes=1)
    tick(engine)
    assert row(conn, created.id).stopped
    stopped_at = row(conn, created.id).stopped_at

    channel.always_fail_with(None)  # el dueño desbloquea el bot
    clock.advance(hours=2)
    assert tick(engine) == 0  # detenido: no sale solo
    assert reminders.reactivate(conn, created.id) is True
    reactivated = row(conn, created.id)
    assert (reactivated.stopped, reactivated.attempts, reactivated.first_failed_at) == (
        False,
        0,
        None,
    )
    assert reactivated.stopped_at == stopped_at  # la marca histórica se conserva
    assert tick(engine) == 1
    assert [text for _, text, _, _ in channel.choices] == [
        "<b>x</b>\n\nRecordatorio <i>(retrasado)</i>"
    ]


def test_reactivar_lo_que_no_esta_detenido_no_hace_nada(conn, clock):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    assert reminders.reactivate(conn, created.id) is False
    assert reminders.reactivate(conn, 999) is False


def test_reactivar_una_fila_de_serie_no_crea_otra_siguiente(conn, clock, engine, channel):
    start = clock() + timedelta(minutes=1)
    first = reminders.create_reminder(conn, "serie", start, clock, rrule="FREQ=DAILY")
    channel.always_fail_with(PermanentChannelError("bot_blocked"))
    clock.advance(minutes=1)
    tick(engine)
    assert len(all_rows(conn)) == 2  # al detenerse ya creó la siguiente

    channel.always_fail_with(None)
    clock.advance(minutes=5)
    assert reminders.reactivate(conn, first.id) is True
    assert tick(engine) == 1
    rows = all_rows(conn)
    assert len(rows) == 2  # M13: reactivar y enviar NO crea una tercera
    assert [r.status for r in rows] == ["sent", "pending"]
    assert rows[1].fire_at_utc == to_utc_iso(start + timedelta(days=1))


# --- Refinamientos: futuros sin estampar, caídas separadas, códigos y atomicidad ----------------


def test_un_recordatorio_futuro_no_se_estampa_con_first_failed_at(conn, clock, engine, channel):
    due = reminders.create_reminder(conn, "ya", clock() + timedelta(minutes=1), clock)
    future = reminders.create_reminder(conn, "luego", clock() + timedelta(hours=3), clock)
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    tick(engine)
    assert row(conn, due.id).first_failed_at is not None
    assert row(conn, future.id).first_failed_at is None  # aún no le toca: el canal no le falló


def test_dos_caidas_separadas_no_se_suman_al_horizonte(conn, clock, engine, channel):
    """1 h de caída, recuperación y luego 23 h de caída: ninguna llega a las 24 h propias."""

    def create_pair(label: str) -> list[int]:
        return [
            reminders.create_reminder(
                conn, f"{label}{i}", clock() + timedelta(minutes=1), clock, priority=2
            ).id
            for i in range(2)
        ]

    def run(duration: timedelta) -> None:
        end = clock() + duration
        while clock() < end:
            tick(engine)
            clock.advance(seconds=30)

    first = create_pair("a")
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    run(timedelta(hours=1))
    assert all(row(conn, i).first_failed_at is not None for i in first)

    channel.always_fail_with(None)  # recuperación: salen los dos
    run(timedelta(minutes=6))
    assert all(
        row(conn, i).status == "sent" and row(conn, i).first_failed_at is None for i in first
    )
    for reminder_id in first:
        reminders.mark_done(conn, reminder_id)  # sin esto insistirían

    second = create_pair("b")
    channel.always_fail_with(DOWN)
    clock.advance(minutes=1)
    run(timedelta(hours=23))
    assert all(not r.stopped for r in all_rows(conn))  # ninguno se detuvo
    assert all(row(conn, i).status == "pending" for i in second)


def test_el_motivo_de_detencion_es_un_codigo_estable(conn, clock, engine, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    channel.always_fail_with(PermanentChannelError("chat_not_found"))
    clock.advance(minutes=1)
    tick(engine)
    assert row(conn, created.id).stop_reason == "permanent:chat_not_found"


def test_detener_y_crear_la_siguiente_de_la_serie_es_una_transaccion(
    conn, clock, engine, channel, monkeypatch
):
    start = clock() + timedelta(minutes=1)
    first = reminders.create_reminder(conn, "serie", start, clock, rrule="FREQ=DAILY")
    channel.always_fail_with(PermanentChannelError("bot_blocked"))
    clock.advance(minutes=1)

    def boom(*args, **kwargs):
        raise RuntimeError("falla al calcular la siguiente")

    monkeypatch.setattr(reminders, "next_occurrence", boom)
    tick(engine)  # no revienta el tick
    rows = all_rows(conn)
    assert len(rows) == 1  # no hay siguiente...
    stored = rows[0]
    assert (stored.stop_reason, stored.stopped_at) == (None, None)  # ...ni quedó detenido a medias

    monkeypatch.undo()
    clock.advance(seconds=30)
    tick(engine)  # el siguiente tick lo completa entero
    rows = all_rows(conn)
    assert len(rows) == 2
    assert row(conn, first.id).stop_reason == "permanent:bot_blocked"
    assert row(conn, first.id).stopped_at is not None  # stopped_at => ya se generó la siguiente


def test_todas_las_pruebas_del_modulo_comparten_un_solo_bucle(conn, clock, engine, channel):
    """Garantía del arreglo del cuelgue en Windows: un bucle por módulo, no uno por tick."""
    loops: list[int] = []
    original = channel.send_choices

    async def spy(*args, **kwargs):
        loops.append(id(asyncio.get_running_loop()))
        return await original(*args, **kwargs)

    channel.send_choices = spy
    for minutes in (1, 2):
        reminders.create_reminder(conn, f"r{minutes}", clock() + timedelta(minutes=minutes), clock)
    clock.advance(minutes=1)
    tick(engine)
    clock.advance(minutes=1)
    tick(engine)
    assert len(loops) == 2 and len(set(loops)) == 1
    assert loops[0] == id(_runner.get_loop())
