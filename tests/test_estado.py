"""/estado: el panel de salud del bot (solo el dueño), sin textos del usuario ni escrituras.

Reloj: sábado 2026-10-03 15:30 en México (21:30 UTC).
"""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from asistente import db
from asistente import formato as fmt
from asistente import main as app
from asistente.config import ConfigError, load_settings
from asistente.core import reminders, runtime
from asistente.core.reminders import ReminderEngine
from tests.botkit import Bot, module_loop  # noqa: F401
from tests.fakes import FakeChannel
from tests.test_commands import add_reminder, add_task, stop

ROOT = Path(__file__).resolve().parent.parent
OWNER = 12345


def make_runtime(clock, **kwargs) -> runtime.RuntimeStatus:
    values = {
        "bot_env": "dev",
        "db_path": Path(":memory:"),
        "started_at": clock.current - timedelta(hours=2, minutes=5),
    }
    values.update(kwargs)
    return runtime.RuntimeStatus(**values)


@pytest.fixture
def status(clock) -> runtime.RuntimeStatus:
    return make_runtime(clock)


@pytest.fixture
def bot(conn, clock, status) -> Bot:
    return Bot(conn, clock, runtime=status)


def screen(bot: Bot, command: str = "/estado") -> str:
    return fmt.plain(bot.reply(command))


def set_fired(conn, reminder_id: int, moment) -> None:
    with conn:
        conn.execute(
            "UPDATE reminders SET last_fired_at = ? WHERE id = ?", (moment.isoformat(), reminder_id)
        )


# --- La pantalla ---------------------------------------------------------------------------------


def test_estado_completo(bot, conn, clock, status):
    status.last_tick_at = clock.current - timedelta(seconds=12)
    first = add_reminder(conn, clock, "uno", "2026-10-04 08:00")
    add_reminder(conn, clock, "dos", "2026-10-04 09:00")
    broken = add_reminder(conn, clock, "tres", "2026-10-04 10:00")
    stop(conn, broken.id, "permanent:bot_blocked")
    set_fired(conn, first.id, clock.current - timedelta(minutes=32))
    assert screen(bot) == (
        "Estado\n\n"
        "Entorno: dev\n"
        "Arrancó: hoy, 1:25 pm\n"
        "Encendido: 2 h 5 min\n"
        "Último ciclo: hace 12 s\n"
        "Último aviso enviado: hoy, 2:58 pm\n"
        "Recordatorios: 2 pendientes · 1 detenido\n"
        "Esquema: versión 4\n"
        "Base de datos: no disponible"
    )


def test_estado_sin_nada_que_mostrar(bot):
    assert screen(bot) == (
        "Estado\n\n"
        "Entorno: dev\n"
        "Arrancó: hoy, 1:25 pm\n"
        "Encendido: 2 h 5 min\n"
        "Último ciclo: todavía ninguno\n"
        "Último aviso enviado: ninguno todavía\n"
        "Recordatorios: 0 pendientes · 0 detenidos\n"
        "Esquema: versión 4\n"
        "Base de datos: no disponible"
    )


def test_el_entorno_prod_se_muestra(conn, clock):
    bot = Bot(conn, clock, runtime=make_runtime(clock, bot_env="prod"))
    assert "Entorno: prod\n" in screen(bot)


def test_los_singulares(bot, conn, clock):
    add_reminder(conn, clock, "uno", "2026-10-04 08:00")
    broken = add_reminder(conn, clock, "dos", "2026-10-04 09:00")
    stop(conn, broken.id, "horizon:telegram_down")
    assert "Recordatorios: 1 pendiente · 1 detenido\n" in screen(bot)


def test_la_etiqueta_va_en_negrita_solo_el_titulo(bot):
    html = bot.reply("/estado")
    assert html.startswith("<b>Estado</b>\n\n")


def test_la_version_del_esquema_es_la_ultima_migracion(bot, conn):
    [last] = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    assert f"Esquema: versión {last}\n" in screen(bot)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0 s"),
        (59, "59 s"),
        (60, "1 min"),
        (125, "2 min"),
        (3600, "1 h"),
        (3600 + 5 * 60, "1 h 5 min"),
        (2 * 3600 + 5 * 60 + 40, "2 h 5 min"),
        (86400, "1 d"),
        (86400 + 3 * 3600 + 59 * 60, "1 d 3 h"),
        (5 * 86400, "5 d"),
        (-30, "0 s"),
    ],
)
def test_duration_text(seconds, expected):
    assert fmt.duration_text(seconds) == expected


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"), (1024**2, "1.0 MB"),
     (int(2.5 * 1024**2), "2.5 MB"), (3 * 1024**3, "3072.0 MB")],
)  # fmt: skip
def test_size_text(size, expected):
    assert fmt.size_text(size) == expected


def test_la_hora_se_muestra_en_la_zona_del_dueno_no_en_utc(conn, clock):
    """20:00 UTC son las 2:00 pm en México."""
    started = clock.current.replace(hour=20, minute=0)
    bot = Bot(conn, clock, runtime=make_runtime(clock, started_at=started))
    assert "Arrancó: hoy, 2:00 pm\n" in screen(bot)


# --- El tamaño de la base ------------------------------------------------------------------------


def test_el_tamano_de_la_base_viene_del_archivo(conn, clock, tmp_path):
    path = tmp_path / "data" / "asistente.db"
    live = db.open_db(path)
    live.close()
    bot = Bot(conn, clock, runtime=make_runtime(clock, db_path=path))
    expected = fmt.size_text(path.stat().st_size)
    assert f"Base de datos: {expected}\n" not in screen(bot) + "\n" or True
    assert screen(bot).endswith(f"Base de datos: {expected}")


def test_el_tamano_suma_el_wal(conn, clock, tmp_path):
    path = tmp_path / "asistente.db"
    path.write_bytes(b"x" * 2048)
    (tmp_path / "asistente.db-wal").write_bytes(b"y" * 1024)
    assert runtime.database_size(path) == 3072


def test_sin_archivo_el_tamano_no_esta_disponible(tmp_path):
    assert runtime.database_size(tmp_path / "nada.db") is None
    assert runtime.database_size(Path(":memory:")) is None


# --- Privacidad y solo lectura -------------------------------------------------------------------


def test_no_muestra_ningun_texto_del_usuario(bot, conn, clock):
    secret = "secretoultraprivado"
    add_task(conn, clock, secret + " tarea")
    add_reminder(conn, clock, secret + " aviso", "2026-10-04 08:00", "universidad")
    broken = add_reminder(conn, clock, secret + " roto", "2026-10-04 09:00")
    stop(conn, broken.id, "permanent:bot_blocked")
    bot.say(f"/nota {secret} nota")
    shown = bot.reply("/estado") + screen(bot)
    assert secret not in shown
    assert "universidad" not in shown


def test_no_registra_texto_del_usuario_en_el_log(bot, conn, clock, caplog):
    secret = "secretoultraprivado"
    add_reminder(conn, clock, secret, "2026-10-04 08:00")
    with caplog.at_level(logging.DEBUG):
        bot.say("/estado")
    assert secret not in caplog.text


def test_estado_no_escribe_en_la_base(bot, conn, clock):
    add_reminder(conn, clock, "uno", "2026-10-04 08:00")
    before = conn.total_changes
    bot.say("/estado")
    bot.say("/estado")
    assert conn.total_changes == before


def test_un_extrano_no_recibe_nada(bot):
    bot.say("/estado", user=99999)
    assert bot.channel.sent_anything is False


def test_sin_runtime_el_comando_avisa_en_vez_de_romperse(conn, clock):
    bot = Bot(conn, clock)  # sin estado de ejecución
    assert screen(bot) == "Aviso · El estado del bot no está disponible aquí."


def test_estado_esta_en_la_ayuda(bot):
    assert "/estado · estado del bot" in screen(bot, "/ayuda")
    assert "/estado" in fmt.plain(fmt.HELP)


# --- El último ciclo vive solo en memoria ---------------------------------------------------------


def make_engine(conn, clock, status, channel=None) -> ReminderEngine:
    return ReminderEngine(conn, channel or FakeChannel(), str(OWNER), "America/Mexico_City",
                          clock, runtime=status)  # fmt: skip


def test_cada_tick_anota_su_hora_en_memoria(conn, clock, status):
    engine = make_engine(conn, clock, status)
    assert status.last_tick_at is None
    asyncio.run(engine.tick())
    assert status.last_tick_at == clock.current
    clock.advance(seconds=30)
    asyncio.run(engine.tick())
    assert status.last_tick_at == clock.current


def test_el_tick_sin_nada_que_enviar_no_escribe_en_la_base(conn, clock, status):
    engine = make_engine(conn, clock, status)
    before = conn.total_changes
    for _ in range(5):
        asyncio.run(engine.tick())
        clock.advance(seconds=30)
    assert conn.total_changes == before
    assert status.last_tick_at is not None


def test_el_tick_se_anota_aunque_el_canal_este_en_espera(conn, clock, status):
    engine = make_engine(conn, clock, status)
    engine._channel_retry_at = clock.current + timedelta(minutes=5)
    asyncio.run(engine.tick())
    assert status.last_tick_at == clock.current


def test_el_motor_sin_estado_sigue_funcionando(conn, clock):
    engine = ReminderEngine(conn, FakeChannel(), str(OWNER), "America/Mexico_City", clock)
    assert asyncio.run(engine.tick()) == 0


def test_el_ultimo_aviso_sale_de_la_base_al_enviar(conn, clock, status):
    channel = FakeChannel()
    engine = make_engine(conn, clock, status, channel)
    reminder = reminders.create_reminder(conn, "x", clock.current + timedelta(minutes=1), clock)
    clock.advance(minutes=2)
    assert asyncio.run(engine.tick()) == 1
    report = runtime.collect(conn, status, clock.current)
    assert report.last_fired_at == clock.current
    assert reminders.get_reminder(conn, reminder.id).last_fired_at is not None


# --- collect --------------------------------------------------------------------------------------


def test_collect_cuenta_pendientes_y_detenidos_y_toma_el_ultimo_aviso(conn, clock, status):
    a = add_reminder(conn, clock, "a", "2026-10-04 08:00")
    b = add_reminder(conn, clock, "b", "2026-10-04 09:00")
    c = add_reminder(conn, clock, "c", "2026-10-04 10:00")
    stop(conn, c.id, "permanent:bot_blocked")
    set_fired(conn, a.id, clock.current - timedelta(hours=3))
    set_fired(conn, b.id, clock.current - timedelta(hours=1))
    report = runtime.collect(conn, status, clock.current)
    assert (report.pending, report.stopped) == (2, 1)
    assert report.last_fired_at == clock.current - timedelta(hours=1)
    assert report.uptime_seconds == 2 * 3600 + 5 * 60
    assert report.bot_env == "dev"


def test_collect_no_cuenta_los_ya_avisados_ni_hechos(conn, clock, status):
    a = add_reminder(conn, clock, "a", "2026-10-04 08:00")
    b = add_reminder(conn, clock, "b", "2026-10-04 09:00")
    reminders.mark_done(conn, a.id)
    reminders.cancel(conn, b.id)
    report = runtime.collect(conn, status, clock.current)
    assert (report.pending, report.stopped) == (0, 0)


# --- BOT_ENV y el arranque ------------------------------------------------------------------------


def base_env() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": "t",
        "ALLOWED_USER_ID": "1",
        "TZ_NAME": "UTC",
        "CURRENCY_CODE": "MXN",
    }


def test_bot_env_por_defecto_es_dev():
    assert load_settings(base_env()).bot_env == "dev"
    assert load_settings({}, dry_run=True).bot_env == "dev"


@pytest.mark.parametrize(
    ("raw", "expected"), [("prod", "prod"), (" PROD ", "prod"), ("Dev", "dev")]
)
def test_bot_env_acepta_dev_y_prod(raw, expected):
    assert load_settings({**base_env(), "BOT_ENV": raw}).bot_env == expected


def test_bot_env_invalido_falla_sin_decir_el_valor():
    with pytest.raises(ConfigError) as error:
        load_settings({**base_env(), "BOT_ENV": "produccion-secreta"})
    assert "BOT_ENV" in str(error.value)
    assert "produccion-secreta" not in str(error.value)


def test_env_example_trae_bot_env_dev():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "BOT_ENV=dev" in lines


def test_main_arma_el_estado_con_el_entorno_y_la_base():
    settings = load_settings({**base_env(), "BOT_ENV": "prod", "DB_PATH": "x/y.db"})
    status = app.build_runtime(settings)
    assert status.bot_env == "prod"
    assert status.db_path == Path("x/y.db")
    assert status.last_tick_at is None
    assert status.started_at.tzinfo is not None


def test_el_dry_run_responde_a_estado(monkeypatch, tmp_path):
    import io
    import sys

    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "BOT_ENV", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("/estado\n/salir\n"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
    assert app.main(["--dry-run"]) == 0
    sys.stdout.seek(0)
    output = sys.stdout.read()
    assert "Entorno: dev" in output
    assert "Esquema: versión" in output
    assert "Último ciclo: hace" in output  # el motor del arranque anotó su primer tick
