"""Bloque 6, punto 5: `scripts/dev_remind_me.py` crea un recordatorio de prueba en N minutos.

Se prueba SIEMPRE con una base temporal (`DB_PATH` + `chdir`): nunca con la base real ni con el
`.env` del dueño.
"""

import ast
import asyncio
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from asistente import db
from asistente.core import reminders
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import from_utc_iso, local_to_utc
from tests.fakes import FakeChannel, FakeClock

TZ = "America/Mexico_City"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dev_remind_me.py"


def load_script():
    spec = importlib.util.spec_from_file_location("dev_remind_me", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return load_script()


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Entorno aislado: base temporal, sin `.env` en el directorio actual."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "prueba.db"))
    monkeypatch.setenv("TZ_NAME", TZ)
    for name in ("DRY_RUN", "TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "prueba.db"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(local_to_utc(datetime(2026, 10, 3, 15, 30), TZ))  # sábado 15:30 en México


def stored(db_path: Path) -> list[reminders.Reminder]:
    conn = db.open_db(db_path)
    try:
        return [
            reminders.get_reminder(conn, r["id"]) for r in conn.execute("SELECT id FROM reminders")
        ]
    finally:
        conn.close()


def test_crea_un_recordatorio_en_n_minutos_en_la_base_de_db_path(script, env, clock, capsys):
    assert script.main(["15"], now=clock) == 0
    (created,) = stored(env)
    assert created.text == script.DEFAULT_TEXT
    assert from_utc_iso(created.fire_at_utc) == clock() + timedelta(minutes=15)
    assert (created.status, created.priority, created.rrule) == ("pending", 1, None)
    out = capsys.readouterr().out
    assert f"#{created.id}" in out
    assert str(env) in out  # dice en QUÉ base escribió
    assert "3:45 pm" in out  # y a qué hora local sale


def test_acepta_texto_propio(script, env, clock):
    assert script.main(["5", "llevar tarea de cálculo"], now=clock) == 0
    assert stored(env)[0].text == "llevar tarea de cálculo"


def test_el_texto_con_varias_palabras_sin_comillas_tambien_vale(script, env, clock):
    assert script.main(["5", "llevar", "tarea"], now=clock) == 0
    assert stored(env)[0].text == "llevar tarea"


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.5", ""])
def test_minutos_invalidos_no_crean_nada(script, env, clock, bad):
    with pytest.raises(SystemExit) as caught:
        script.main([bad], now=clock)
    assert caught.value.code == 2
    assert not env.exists() or stored(env) == []


def test_sin_argumentos_no_crea_nada(script, env, clock):
    with pytest.raises(SystemExit) as caught:
        script.main([], now=clock)
    assert caught.value.code == 2


def test_avisa_si_la_hora_cae_en_horas_de_silencio(script, env, clock, capsys):
    clock.current = local_to_utc(datetime(2026, 10, 3, 21, 50), TZ)  # silencio: 22:00-07:00
    assert script.main(["30"], now=clock) == 0
    out = capsys.readouterr().out
    assert "Ojo" in out and "silencio" in out and "--urgente" in out
    assert stored(env)[0].priority == 1


def test_urgente_usa_prioridad_2_y_no_avisa_del_silencio(script, env, clock, capsys):
    clock.current = local_to_utc(datetime(2026, 10, 3, 21, 50), TZ)
    assert script.main(["30", "--urgente"], now=clock) == 0
    assert stored(env)[0].priority == 2
    assert "Ojo" not in capsys.readouterr().out


def test_sin_aviso_de_silencio_en_horas_normales(script, env, clock, capsys):
    script.main(["10"], now=clock)
    assert "Ojo" not in capsys.readouterr().out


def test_el_motor_lo_envia_a_su_hora_de_punta_a_punta(script, env, clock):
    script.main(["10", "prueba de punta a punta"], now=clock)
    conn = db.open_db(env)
    try:
        channel = FakeChannel()
        engine = ReminderEngine(conn, channel, "42", TZ, clock)
        assert asyncio.run(engine.tick()) == 0  # aún no es la hora
        clock.advance(minutes=10)
        assert asyncio.run(engine.tick()) == 1
        assert channel.choices[0][1] == "⏰ prueba de punta a punta"
    finally:
        conn.close()


def test_no_importa_nada_de_llm_ni_de_clasificacion_ni_de_telegram():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    forbidden = ("anthropic", "telegram", "asistente.llm", "asistente.classify", "httpx")
    assert not [r for r in roots if r.startswith(forbidden)]
