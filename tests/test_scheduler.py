"""Bloque 6, punto 2: el tick de recordatorios corre solo en Telegram y en consola.

- Telegram: `job_queue.run_repeating(interval=30, first=0)` con `max_instances=1` y `coalesce`.
- Consola: una tarea asyncio con el mismo ritmo.
- Un fallo dentro del tick se registra (solo el tipo) y no mata el job.
"""

import asyncio
import io
import logging
import sys
import time
from datetime import timedelta

from asistente import db
from asistente import main as app
from asistente.channels import telegram as tg
from asistente.channels.base import TICK_INTERVAL_SECONDS
from asistente.channels.console import ConsoleChannel
from asistente.core import reminders
from asistente.timeutil import now as real_now


async def _nothing(*args) -> None:
    return None


def _telegram_with_spy(monkeypatch):
    """Canal de Telegram sin red, con un espía sobre `run_repeating`."""
    channel = tg.TelegramChannel("123456:token-falso", allowed_user_id=1)
    monkeypatch.setattr(channel._application, "add_handler", lambda *a, **k: None)
    monkeypatch.setattr(channel._application, "add_error_handler", lambda cb: None)
    monkeypatch.setattr(channel._application, "run_polling", lambda: None)
    job_queue = channel._application.job_queue
    calls: list[dict] = []
    original = type(job_queue).run_repeating

    def spy(self, callback, interval, **kwargs):
        calls.append({"interval": interval, **kwargs})
        return original(self, callback, interval, **kwargs)

    # JobQueue no admite reemplazar métodos en la instancia: se parchea la clase.
    monkeypatch.setattr(type(job_queue), "run_repeating", spy)
    return channel, job_queue, calls


# --- Telegram ---------------------------------------------------------------------------------


def test_telegram_registra_el_tick_cada_30_segundos_y_al_arrancar(monkeypatch):
    channel, job_queue, calls = _telegram_with_spy(monkeypatch)
    channel.run_polling(_nothing, _nothing, _nothing)
    assert len(calls) == 1
    assert calls[0]["interval"] == TICK_INTERVAL_SECONDS == 30
    assert calls[0]["first"] == 0  # dispara al arrancar: recuperación tras una caída
    assert calls[0]["job_kwargs"] == {"max_instances": 1, "coalesce": True}


def test_el_job_no_se_solapa_consigo_mismo(monkeypatch):
    """Dos ticks a la vez no existen: una sola instancia y los disparos atrasados se funden."""
    channel, job_queue, _ = _telegram_with_spy(monkeypatch)
    channel.run_polling(_nothing, _nothing, _nothing)
    (job,) = job_queue.jobs()
    assert job.job.max_instances == 1
    assert job.job.coalesce is True
    assert job.job.trigger.interval == timedelta(seconds=30)


def test_el_job_llama_a_on_tick(monkeypatch):
    channel, job_queue, _ = _telegram_with_spy(monkeypatch)
    calls: list[int] = []

    async def on_tick() -> int:
        calls.append(1)
        return 1

    channel.run_polling(_nothing, _nothing, on_tick)
    (job,) = job_queue.jobs()
    asyncio.run(job.callback(None))
    assert calls == [1]


def test_un_fallo_en_el_tick_se_registra_y_no_mata_el_job(monkeypatch, caplog):
    channel, job_queue, _ = _telegram_with_spy(monkeypatch)
    calls: list[int] = []

    async def on_tick() -> int:
        calls.append(1)
        raise RuntimeError("secreto-médico")

    channel.run_polling(_nothing, _nothing, on_tick)
    (job,) = job_queue.jobs()
    with caplog.at_level(logging.DEBUG):
        asyncio.run(job.callback(None))  # no debe lanzar
        asyncio.run(job.callback(None))  # y el siguiente disparo sigue funcionando
    assert calls == [1, 1]
    assert "RuntimeError" in caplog.text
    assert "secreto-médico" not in caplog.text


# --- Consola ----------------------------------------------------------------------------------


def _serve(on_tick, lines: list[str], tick_interval: float, delay: float = 0.0) -> list[str]:
    """Corre la consola con entradas que tardan `delay` s cada una; devuelve lo impreso."""
    pending = list(lines)

    def input_fn(prompt: str) -> str:
        time.sleep(delay)
        if not pending:
            raise EOFError
        return pending.pop(0)

    output: list[str] = []
    channel = ConsoleChannel("1", input_fn=input_fn, output_fn=output.append)
    asyncio.run(channel.serve(_nothing, _nothing, on_tick, tick_interval=tick_interval))
    return output


def test_la_consola_lanza_un_tick_nada_mas_arrancar():
    calls: list[int] = []

    async def on_tick() -> int:
        calls.append(1)
        return 0

    _serve(on_tick, ["/salir"], tick_interval=60)
    assert calls == [1]


def test_la_consola_repite_el_tick_con_el_intervalo():
    calls: list[int] = []

    async def on_tick() -> int:
        calls.append(1)
        return 0

    _serve(on_tick, ["hola"], tick_interval=0.02, delay=0.3)
    assert len(calls) >= 3


def test_la_consola_no_solapa_ticks_lentos():
    running = 0
    peak = 0

    async def on_tick() -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.1)
        running -= 1
        return 0

    _serve(on_tick, ["hola"], tick_interval=0.01, delay=0.4)
    assert peak == 1


def test_en_la_consola_un_fallo_del_tick_no_mata_el_bucle(caplog):
    calls: list[int] = []

    async def on_tick() -> int:
        calls.append(1)
        raise RuntimeError("secreto-médico")

    with caplog.at_level(logging.DEBUG):
        _serve(on_tick, ["hola"], tick_interval=0.02, delay=0.3)
    assert len(calls) >= 3
    assert "RuntimeError" in caplog.text
    assert "secreto-médico" not in caplog.text


def test_la_consola_cancela_la_tarea_al_salir():
    calls: list[int] = []

    async def on_tick() -> int:
        calls.append(1)
        return 0

    async def scenario() -> None:
        channel = ConsoleChannel("1", input_fn=lambda p: "/salir", output_fn=lambda t: None)
        await channel.serve(_nothing, _nothing, on_tick, tick_interval=0.01)
        seen = len(calls)
        await asyncio.sleep(0.1)
        assert len(calls) == seen  # nadie sigue llamando al tick tras salir
        assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []

    asyncio.run(scenario())


# --- main.py conecta el motor con el canal ------------------------------------------------------


def _due_reminder(db_path, text: str = "llevar tarea") -> None:
    """Un recordatorio ya vencido (como tras una caída); prioridad 2 para saltarse el silencio."""
    conn = db.open_db(db_path)
    try:

        def three_hours_ago():
            return real_now() - timedelta(hours=3)

        reminders.create_reminder(
            conn, text, three_hours_ago() + timedelta(minutes=1), three_hours_ago, priority=2
        )
    finally:
        conn.close()


def test_el_dry_run_envia_los_vencidos_al_arrancar(monkeypatch, tmp_path):
    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _due_reminder(tmp_path / "data" / "dry_run.db")
    monkeypatch.setattr(sys, "stdin", io.StringIO("/salir\n"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    assert app.main(["--dry-run"]) == 0

    sys.stdout.seek(0)
    output = sys.stdout.read()
    assert "[reminder] ⏰ llevar tarea (retrasado)" in output
    assert "1) ✅ Hecho" in output


def test_main_pasa_on_tick_a_telegram_y_el_tick_envia_los_vencidos(monkeypatch, tmp_path):
    for name, value in (
        ("TELEGRAM_BOT_TOKEN", "123456:token-falso"),
        ("ALLOWED_USER_ID", "7"),
        ("TZ_NAME", "America/Mexico_City"),
        ("CURRENCY_CODE", "MXN"),
        ("DB_PATH", str(tmp_path / "real.db")),
    ):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.chdir(tmp_path)  # sin .env aquí
    _due_reminder(tmp_path / "real.db")

    sent: list[tuple[str, str, str]] = []
    captured: dict = {}

    class FakeTelegram:
        def __init__(self, token: str, allowed_user_id: int) -> None:
            captured["init"] = (token, allowed_user_id)

        async def send_choices(self, to, text, choices, kind="reply") -> None:
            sent.append((to, text, kind))

        async def send_text(self, to, text, kind="reply") -> None:
            sent.append((to, text, kind))

        def run_polling(self, on_message, on_choice, on_tick, tick_seconds) -> None:
            captured["on_tick"] = on_tick
            captured["tick_seconds"] = tick_seconds
            asyncio.run(on_tick())  # lo que haría `first=0` del job al arrancar

    monkeypatch.setattr(tg, "TelegramChannel", FakeTelegram)

    assert app.main([]) == 0
    assert captured["init"] == ("123456:token-falso", 7)
    assert captured["tick_seconds"] == 30  # el valor por defecto de TICK_SECONDS
    assert sent == [("7", "⏰ llevar tarea (retrasado)", "reminder")]
