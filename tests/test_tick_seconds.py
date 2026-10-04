"""TICK_SECONDS: el ritmo del tick se configura (5-60 s) y NADA del motor depende de él.

La espera entre reintentos y el umbral de «(retrasado)» están en SEGUNDOS, no en vueltas de tick:
con ticks de 10 s y de 30 s salen en los mismos instantes. Reloj: sábado 2026-10-03 15:30 México.
"""

import asyncio
import logging
from datetime import timedelta

import pytest

from asistente import main as app
from asistente.channels import base
from asistente.channels.base import TransientChannelError, run_tick_safely
from asistente.config import (
    DEFAULT_TICK_SECONDS,
    MAX_TICK_SECONDS,
    MIN_TICK_SECONDS,
    ConfigError,
    load_settings,
)
from asistente.core import reminders
from asistente.core.reminders import LATE_GRACE, ReminderEngine, backoff_seconds
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"
USER = "42"
DOWN = TransientChannelError("telegram_down")
ENV = {"TELEGRAM_BOT_TOKEN": "t", "ALLOWED_USER_ID": "1", "TZ_NAME": TZ, "CURRENCY_CODE": "MXN"}

_runner: asyncio.Runner | None = None


@pytest.fixture(scope="module", autouse=True)
def _module_loop():
    global _runner
    with asyncio.Runner() as runner:
        _runner = runner
        yield runner
    _runner = None


def run(coroutine):
    assert _runner is not None
    return _runner.run(coroutine)


# --- Configuración -----------------------------------------------------------------------------


def test_por_defecto_son_30_segundos():
    assert load_settings(ENV).tick_seconds == 30 == DEFAULT_TICK_SECONDS
    assert base.TICK_INTERVAL_SECONDS == DEFAULT_TICK_SECONDS


@pytest.mark.parametrize("raw", ["5", "10", "30", "60", " 15 "])
def test_valores_validos(raw):
    assert load_settings({**ENV, "TICK_SECONDS": raw}).tick_seconds == int(raw)


@pytest.mark.parametrize("raw", ["4", "61", "0", "-10", "abc", "7.5", "30s"])
def test_valores_invalidos_se_rechazan_sin_adivinar(raw):
    with pytest.raises(ConfigError, match="TICK_SECONDS"):
        load_settings({**ENV, "TICK_SECONDS": raw})


def test_un_valor_vacio_cuenta_como_ausente():
    assert load_settings({**ENV, "TICK_SECONDS": ""}).tick_seconds == 30


def test_los_limites_son_5_y_60():
    assert (MIN_TICK_SECONDS, MAX_TICK_SECONDS) == (5, 60)


def test_la_consola_recibe_el_ritmo_configurado(monkeypatch, tmp_path, conn):
    from asistente.channels import console

    seen = {}

    async def fake_serve(self, on_message, on_choice, on_tick, tick_interval=None):
        seen["interval"] = tick_interval

    monkeypatch.setattr(console.ConsoleChannel, "serve", fake_serve)
    settings = load_settings({**ENV, "TICK_SECONDS": "12"}, dry_run=True)
    app.run_console(settings, conn)
    assert seen["interval"] == 12


def test_telegram_recibe_el_ritmo_configurado(monkeypatch, conn):
    from asistente.channels import telegram

    seen = {}

    class FakeTelegram:
        def __init__(self, token, allowed_user_id):
            pass

        def run_polling(self, on_message, on_choice, on_tick, tick_seconds=None):
            seen["interval"] = tick_seconds

    monkeypatch.setattr(telegram, "TelegramChannel", FakeTelegram)
    app.run_telegram(load_settings({**ENV, "TICK_SECONDS": "45"}), conn)
    assert seen["interval"] == 45


# --- El motor mide en segundos, no en vueltas ---------------------------------------------------


@pytest.mark.parametrize("tick_seconds", [10, 30])
def test_la_espera_entre_reintentos_es_en_segundos_no_en_vueltas(conn, clock, tick_seconds):
    channel = ScriptedChannel()
    channel.always_fail_with(DOWN)
    engine = ReminderEngine(conn, channel, USER, TZ, clock)
    reminders.create_reminder(conn, "x", clock() + timedelta(seconds=1), clock, priority=2)
    clock.advance(seconds=1)
    start = clock()

    attempts_at: list[int] = []
    seen = 0
    while clock() - start <= timedelta(seconds=460):
        run(engine.tick())
        if len(channel.attempts) > seen:
            seen = len(channel.attempts)
            attempts_at.append(int((clock() - start).total_seconds()))
        clock.advance(seconds=tick_seconds)

    # 30, 60, 120, 240 s de espera: intentos en 0, 30, 90, 210 y 450 s, sea cual sea el tick.
    assert attempts_at == [0, 30, 90, 210, 450]
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [30, 60, 120, 240]


@pytest.mark.parametrize("tick_seconds", [10, 30])
def test_un_aviso_a_tiempo_no_sale_retrasado_con_cualquier_ritmo(conn, clock, tick_seconds):
    channel = ScriptedChannel()
    engine = ReminderEngine(conn, channel, USER, TZ, clock)
    reminders.create_reminder(conn, "a tiempo", clock() + timedelta(seconds=45), clock)

    for _ in range(12):  # hasta 2 min de ticks al ritmo configurado
        run(engine.tick())
        clock.advance(seconds=tick_seconds)

    [(_, text, _, _)] = channel.choices
    assert "(retrasado)" not in text  # a lo sumo llegó tick_seconds tarde: dentro de los 2 min


@pytest.mark.parametrize("tick_seconds", [10, 30])
def test_el_umbral_de_retrasado_es_de_2_minutos_exactos(conn, clock, tick_seconds):
    assert LATE_GRACE == timedelta(minutes=2)
    channel = ScriptedChannel()
    engine = ReminderEngine(conn, channel, USER, TZ, clock)
    due = clock() + timedelta(seconds=10)
    reminders.create_reminder(conn, "justo", due, clock)
    reminders.create_reminder(conn, "tarde", due, clock)
    with conn:  # el segundo se atrasa 1 s más que el umbral
        conn.execute(
            "UPDATE reminders SET fire_at_utc = ? WHERE text = 'tarde'",
            ((due - timedelta(seconds=1)).isoformat(timespec="seconds"),),
        )
    clock.current = due + LATE_GRACE  # exactamente 2 min después de «justo»
    run(engine.tick())
    texts = {text.split(" [")[0] for _, text, _, _ in channel.choices}
    assert "⏰ justo" in texts  # 2 min exactos: todavía no es retraso
    assert "⏰ tarde (retrasado)" in texts  # 2 min y 1 s: sí


# --- Registro ----------------------------------------------------------------------------------


@pytest.fixture
def restore_logging():
    """Parte de un registro «de producción»: raíz en INFO y apscheduler sin nivel propio."""
    names = ("apscheduler", "httpx", "httpcore")
    saved = {name: logging.getLogger(name).level for name in names}
    root = logging.getLogger()
    saved_root = root.level
    root.setLevel(logging.INFO)
    for name in names:
        logging.getLogger(name).setLevel(logging.NOTSET)
    yield
    root.setLevel(saved_root)
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def test_apscheduler_solo_registra_advertencias(restore_logging):
    app.setup_logging("INFO")
    for name in ("apscheduler", "apscheduler.scheduler", "apscheduler.executors.default"):
        logger = logging.getLogger(name)
        assert logger.getEffectiveLevel() == logging.WARNING
        assert not logger.isEnabledFor(logging.INFO)
        assert logger.isEnabledFor(logging.ERROR)


def test_nuestros_propios_errores_siguen_visibles(restore_logging, caplog):
    app.setup_logging("INFO")
    assert logging.getLogger("asistente.channels.base").isEnabledFor(logging.ERROR)

    async def failing_tick():
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="asistente"):
        run(run_tick_safely(failing_tick))
    assert "Fallo en el tick de recordatorios: RuntimeError" in caplog.text
