"""Guardas estructurales del cableado de `main._handlers`.

Un mismo diccionario de cableado alimenta a TODOS los manejadores; si a uno le falta un parámetro
(o le sobra uno), Telegram lo descubre en producción con un `TypeError`. Aquí se comprueba con
`inspect.signature(...).bind`, sin depender de los canales.
"""

import asyncio
import inspect
from functools import partial

import pytest

from asistente import main as app
from asistente.bot.conversation import Conversation
from asistente.channels.base import IncomingChoice, IncomingMessage
from asistente.config import load_settings
from tests.fakes import FakeChannel

ENV = {
    "TELEGRAM_BOT_TOKEN": "t",
    "ALLOWED_USER_ID": "1",
    "TZ_NAME": "America/Mexico_City",
    "CURRENCY_CODE": "MXN",
}


@pytest.fixture
def wired(conn):
    settings = load_settings(ENV)
    runtime = app.build_runtime(settings)
    return app._handlers(settings, conn, FakeChannel(), runtime)


def test_el_cableado_reparte_dos_manejadores(wired):
    assert len(wired) == 2
    assert all(isinstance(handler, partial) for handler in wired)


def test_todo_lo_que_se_reparte_lo_acepta_cada_manejador(wired):
    """El primer argumento (el evento) lo pone el canal; el resto viene del cableado."""
    for handler in wired:
        signature = inspect.signature(handler.func)
        try:
            signature.bind(object(), **handler.keywords)
        except TypeError as error:  # pragma: no cover - el mensaje dice qué falta o sobra
            pytest.fail(f"{handler.func.__name__} no acepta el cableado: {error}")


def test_los_manejadores_reciben_exactamente_el_mismo_cableado(wired):
    message, choice = wired
    assert message.keywords == choice.keywords
    assert set(message.keywords) == {
        "channel", "allowed_user_id", "conn", "now", "tz_name", "conversation", "runtime",
    }  # fmt: skip


def test_nada_requerido_queda_sin_cubrir(wired):
    """Todo parámetro sin valor por defecto (salvo el evento) viene del cableado."""
    for handler in wired:
        params = list(inspect.signature(handler.func).parameters.values())
        required = {p.name for p in params[1:] if p.default is inspect.Parameter.empty}
        assert required <= set(handler.keywords), handler.func.__name__


# --- Una sola conversación compartida (T5) --------------------------------------------------------


def test_en_produccion_se_crea_una_sola_conversacion_para_mensajes_y_botones(wired):
    message, choice = wired
    assert isinstance(message.keywords["conversation"], Conversation)
    assert message.keywords["conversation"] is choice.keywords["conversation"]


def test_se_respeta_la_conversacion_que_se_inyecta(conn):
    mine = Conversation()
    message, choice = app._handlers(load_settings(ENV), conn, FakeChannel(), None, mine)
    assert message.keywords["conversation"] is mine and choice.keywords["conversation"] is mine


def test_dos_cableados_no_comparten_conversacion(conn):
    first = app._handlers(load_settings(ENV), conn, FakeChannel())
    second = app._handlers(load_settings(ENV), conn, FakeChannel())
    assert first[0].keywords["conversation"] is not second[0].keywords["conversation"]


def test_un_boton_atiende_la_tarjeta_que_abrio_un_mensaje(conn):
    """Prueba de comportamiento: el flujo que abre `on_message` lo continúa `on_choice`."""
    channel = FakeChannel()
    on_message, on_choice = app._handlers(load_settings(ENV), conn, channel)
    asyncio.run(on_message(IncomingMessage("t", "1", "comprar leche")))
    [(_, _, choices, _)] = channel.choices
    toast = asyncio.run(on_choice(IncomingChoice("t", "1", choices[0].id, "f1")))
    assert toast is None  # un botón de OTRA conversación daría el aviso de «ya no aplica»
    assert channel.edits or len(channel.choices) > 1  # la tarjeta avanzó


def test_la_conversacion_inyectada_es_la_que_usa_el_manejador_de_mensajes(conn):
    from asistente.timeutil import now

    mine = Conversation()
    on_message, _ = app._handlers(load_settings(ENV), conn, FakeChannel(), None, mine)
    assert mine.current(now) is None
    asyncio.run(on_message(IncomingMessage("t", "1", "comprar leche")))
    assert mine.current(now) is not None  # el flujo abierto vive en la conversación inyectada
