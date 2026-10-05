"""El canal de Telegram con objetos REALES de la librería (`Update.de_json` + `Application`).

Los falsos de `tests/fakes.py` llaman a los manejadores directamente y no ejercitan el cableado de
`main.py` ni el camino de la librería: un cambio de firma pasaba desapercibido. Aquí cada pulsación
y cada mensaje entran como un `Update` real por `Application.process_update`; solo se parchea
`ExtBot` (la clase, como en las pruebas M1) para que no haya red.
"""

import asyncio
import copy
import importlib.util
import logging
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from telegram import Update

from asistente import db
from asistente import main as app_main
from asistente.channels import telegram as tg
from asistente.config import load_settings
from asistente.core import reminders, tasks

OWNER = 12345
NOW = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)
ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:token-falso",
    "ALLOWED_USER_ID": str(OWNER),
    "TZ_NAME": "America/Mexico_City",
    "CURRENCY_CODE": "MXN",
}
USER = {"id": OWNER, "is_bot": False, "first_name": "Yo"}
CHAT = {"id": OWNER, "type": "private", "first_name": "Yo"}
BOT_USER = {"id": 999, "is_bot": True, "first_name": "Bot", "username": "bot_de_prueba"}


def callback_payload(data: str, user: dict = USER, message_id: int = 77) -> dict:
    """Lo que Telegram entrega al pulsar un botón inline de un mensaje del bot."""
    return {
        "update_id": 1,
        "callback_query": {
            "id": "4242",
            "from": user,
            "chat_instance": "-1234567890",
            "data": data,
            "message": {
                "message_id": message_id,
                "date": 1759523400,
                "chat": CHAT,
                "from": BOT_USER,
                "text": "mensaje con botones",
                "reply_markup": {"inline_keyboard": [[{"text": "x", "callback_data": data}]]},
            },
        },
    }


def text_payload(text: str, user: dict = USER) -> dict:
    return {
        "update_id": 2,
        "message": {"message_id": 5, "date": 1759523400, "chat": CHAT, "from": user, "text": text},
    }


class RealPath:
    """Un `TelegramChannel` real cableado como lo hace `main.py`, sin red."""

    def __init__(
        self, conn: sqlite3.Connection, monkeypatch, conversation=None, callbacks=None
    ) -> None:
        self.clock = lambda: NOW
        monkeypatch.setattr(app_main, "now", lambda: self.clock())
        self.channel = tg.TelegramChannel(ENV["TELEGRAM_BOT_TOKEN"], OWNER)
        self.bot = self.channel._application.bot
        self.sends: list[dict] = []
        self.edits: list[dict] = []
        self.answers: list[dict] = []
        counter = iter(range(100, 10_000))

        async def send_message(bot, **kwargs):
            self.sends.append(kwargs)
            return type("Sent", (), {"message_id": next(counter)})()

        async def edit_message_text(bot, **kwargs):
            self.edits.append(kwargs)
            return True

        async def answer_callback_query(bot, callback_query_id, text=None, **kwargs):
            self.answers.append({"id": callback_query_id, "text": text, **kwargs})
            return True

        async def initialize(bot):  # la real llama a getMe (red)
            return None

        for name, function in (
            ("initialize", initialize),
            ("send_message", send_message),
            ("edit_message_text", edit_message_text),
            ("answer_callback_query", answer_callback_query),
        ):
            monkeypatch.setattr(type(self.bot), name, function)
        self.rewire(conn, conversation, callbacks)

    def rewire(self, conn, conversation=None, callbacks=None) -> None:
        """(Re)conecta los manejadores con `main._handlers` sobre otra base y conversación."""
        application = self.channel._application
        application.handlers.clear()
        application.error_handlers.clear()
        if callbacks is None:
            settings = load_settings(ENV)
            runtime = app_main.build_runtime(settings)
            callbacks = app_main._handlers(
                settings, conn, self.channel, runtime, conversation=conversation
            )
        self.channel._register_handlers(*callbacks)

    def process(self, payload: dict) -> None:
        update = Update.de_json(payload, self.bot)
        application = self.channel._application

        async def go() -> None:
            await application.initialize()
            await application.process_update(update)

        asyncio.run(go())

    def press(self, data: str, **kwargs) -> None:
        self.process(callback_payload(data, **kwargs))

    def say(self, text: str, **kwargs) -> None:
        self.process(text_payload(text, **kwargs))


@pytest.fixture
def real(conn, monkeypatch) -> RealPath:
    return RealPath(conn, monkeypatch)


def keyboard_data(call: dict) -> list[str]:
    markup = call.get("reply_markup")
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


def errors_in(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


# --- Paso 1: el diagnóstico del manejador de errores no filtra texto del usuario -----------------


def test_describe_error_da_tipo_y_las_ultimas_5_lineas_de_la_traza():
    def level(n: int):
        if n == 0:
            raise TypeError("cosa")
        level(n - 1)

    try:
        level(8)
    except TypeError as error:
        text = tg.describe_error(error)
    assert text.startswith("TypeError en ")
    frames = re.findall(r"([\w.]+\.py):(\d+) en (\w+)", text)
    assert len(frames) == 5
    assert frames[-1][0] == Path(__file__).name and frames[-1][2] == "level"
    assert "/" not in text and "\\" not in text  # solo el nombre del archivo, sin rutas


def test_describe_error_no_filtra_el_mensaje_ni_los_argumentos():
    secret = "secreto-medico-de-Juan-123"
    try:
        raise TypeError(f"no se puede unir {secret}", secret, {"texto": secret})
    except TypeError as error:
        assert secret not in tg.describe_error(error)


def test_describe_error_sin_traza():
    assert tg.describe_error(ValueError("x")) == "ValueError"


def test_el_manejador_de_errores_registra_las_lineas_y_no_el_texto(conn, monkeypatch, caplog):
    secret = "secreto-medico-de-Juan-123"

    async def boom(message):
        raise TypeError(f"firma rota con {message.text}")

    real = RealPath(conn, monkeypatch, callbacks=(boom, boom))
    with caplog.at_level(logging.INFO):
        real.say(secret)
    [record] = [r for r in caplog.records if "Error en Telegram" in r.getMessage()]
    assert "TypeError en " in record.getMessage()
    assert re.search(r"test_telegram_real\.py:\d+ en boom", record.getMessage())
    assert secret not in caplog.text


# --- Paso 2: las pulsaciones reales por el Application real --------------------------------------


def make_reminder(conn) -> int:
    return reminders.create_reminder(conn, "llamar a mamá", NOW.replace(hour=23), lambda: NOW).id


@pytest.mark.parametrize(
    ("template", "edited"),
    [("rem_done:{id}", True), ("rem_snooze:{id}:10", True), ("rem_tomorrow:{id}", True)],
)
def test_los_botones_del_aviso_de_un_recordatorio(real, conn, caplog, template, edited):
    reminder_id = make_reminder(conn)
    with caplog.at_level(logging.INFO):
        real.press(template.format(id=reminder_id))
    assert errors_in(caplog) == []
    assert len(real.edits) == 1 and real.edits[0]["message_id"] == 77
    assert len(real.answers) == 1  # se quita el relojito del botón


def test_hecho_marca_el_recordatorio_y_edita_el_mensaje(real, conn, caplog):
    reminder_id = make_reminder(conn)
    with caplog.at_level(logging.INFO):
        real.press(f"rem_done:{reminder_id}")
    assert errors_in(caplog) == []
    assert reminders.get_reminder(conn, reminder_id).status == "done"
    assert "Hecho" in real.edits[0]["text"]
    assert real.edits[0].get("reply_markup") is None


def test_un_numero_de_pendientes(real, conn, caplog):
    task = tasks.create_task(conn, "comprar pan", lambda: NOW)
    real.say("/pendientes")
    [number] = keyboard_data(real.sends[0])
    with caplog.at_level(logging.INFO):
        real.press(number)
    assert errors_in(caplog) == []
    assert "Comprar pan" in real.edits[0]["text"]
    assert keyboard_data(real.edits[0])  # Hecha, Descartar, Volver
    assert task.id


def test_un_boton_de_tarjeta(real, conn, caplog):
    with caplog.at_level(logging.INFO):
        real.say("comprar leche")
        buttons = keyboard_data(real.sends[0])
        assert buttons
        real.press(buttons[0])
    assert errors_in(caplog) == []
    assert real.edits  # la tarjeta evolucionó en el mismo mensaje


def test_un_extrano_no_recibe_ni_aviso_breve(real, conn):
    real.press("rem_done:1", user={**USER, "id": 99999})
    real.say("hola", user={**USER, "id": 99999})
    assert real.answers == [] and real.edits == [] and real.sends == []


def test_estado_por_el_camino_real(real, caplog):
    with caplog.at_level(logging.INFO):
        real.say("/estado")
    assert errors_in(caplog) == []
    assert "Entorno" in real.sends[0]["text"]


# --- Paso 3: TODOS los botones de docs/MENSAJES.md, por el camino real ---------------------------

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "docs" / "MENSAJES.md"


def load_catalog_script():
    spec = importlib.util.spec_from_file_location(
        "show_messages_real", ROOT / "scripts" / "show_messages.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clone_state(session, message_id: int, ref: str):
    """Copia de la base y de la conversación tal como están cuando se muestra el botón, para
    pulsarlo sin alterar el catálogo. La tarjeta pasa a llamarse como el `message_id` real."""
    base = db.connect(":memory:")
    session.conn.backup(base)
    conversation = copy.deepcopy(session.conversation)
    flow = conversation._flow
    if flow is not None and flow.message_ref == ref:
        flow.message_ref = str(message_id)
    return base, conversation


def test_todos_los_botones_del_catalogo_se_pulsan_por_el_camino_real(conn, monkeypatch, caplog):
    show = load_catalog_script()
    real = RealPath(conn, monkeypatch)
    pressed: set[str] = set()
    failures: list[str] = []
    count = 0

    def probe(session) -> None:
        nonlocal count
        start = getattr(session, "_probed", 0)
        session._probed = len(session._choices)
        for _text, choices in session._choices[start:]:
            for choice in choices:
                ref = session._id_refs.get(choice.id, show.REF)
                message_id = int(re.sub(r"\D", "", ref) or 77)
                base, conversation = clone_state(session, message_id, ref)
                real.clock = session.clock
                real.rewire(base, conversation)
                caplog.clear()
                real.answers.clear()
                real.press(choice.id, message_id=message_id)
                count += 1
                pressed.add(choice.label)
                if errors_in(caplog) or len(real.answers) != 1:
                    failures.append(f"{choice.label!r} ({choice.id}): {errors_in(caplog)}")
                base.close()

    for name in ("say", "press", "tick"):
        original = getattr(show.Session, name)

        def wrapped(self, *args, _original=original, **kwargs):
            result = _original(self, *args, **kwargs)
            probe(self)
            return result

        monkeypatch.setattr(show.Session, name, wrapped)
    with caplog.at_level(logging.INFO):
        show.render()
    assert failures == []
    assert count > 100
    in_catalog = {
        label
        for line in CATALOG.read_text(encoding="utf-8").splitlines()
        if line.startswith("[")
        for label in re.findall(r"\[([^\[\]]+)\]", line)
    }
    assert in_catalog <= pressed, sorted(in_catalog - pressed)
