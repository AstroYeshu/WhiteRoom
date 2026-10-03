import asyncio
import logging

import pytest

from asistente.bot import handlers
from asistente.bot.choices import MAX_CHOICE_ID_BYTES, decode_choice_id, encode_choice_id
from asistente.channels.base import IncomingChoice, IncomingMessage
from tests.fakes import FakeChannel

OWNER = 12345


def send(text: str, user_ref: str = str(OWNER)) -> FakeChannel:
    channel = FakeChannel()
    asyncio.run(handlers.handle_message(IncomingMessage("fake", user_ref, text), channel, OWNER))
    return channel


def test_start_responde_al_dueno():
    channel = send("/start")
    assert channel.texts == [(str(OWNER), handlers.START_TEXT, "reply")]


def test_ayuda_responde_al_dueno():
    assert send("/ayuda").texts[0][1] == handlers.HELP_TEXT


@pytest.mark.parametrize("text", ["/START", "  /start  ", "/start@mi_bot", "/start con argumentos"])
def test_comando_tolera_mayusculas_espacios_y_nombre_del_bot(text: str):
    assert send(text).texts[0][1] == handlers.START_TEXT


def test_comando_desconocido_y_texto_libre():
    assert send("/inventado").texts[0][1] == handlers.UNKNOWN_COMMAND_TEXT
    assert send("comprar leche").texts[0][1] == handlers.NOT_SAVED_TEXT


@pytest.mark.parametrize("text", ["/start", "/ayuda", "hola"])
def test_usuario_no_autorizado_no_recibe_nada(text: str):
    channel = send(text, user_ref="99999")
    assert channel.sent_anything is False


def test_choice_de_no_autorizado_no_recibe_nada():
    channel = FakeChannel()
    event = IncomingChoice("fake", "99999", "done:1")
    asyncio.run(handlers.handle_choice(event, channel, OWNER))
    assert channel.sent_anything is False


def test_choice_del_dueno_recibe_aviso_amable():
    channel = FakeChannel()
    event = IncomingChoice("fake", str(OWNER), "done:1")
    asyncio.run(handlers.handle_choice(event, channel, OWNER))
    assert channel.texts[0][1] == handlers.STALE_CHOICE_TEXT


def test_el_log_del_rechazo_lleva_el_id_pero_nunca_el_texto(caplog):
    with caplog.at_level(logging.DEBUG):
        send("mi secreto: contraseña123", user_ref="99999")
    assert "99999" in caplog.text
    assert "contraseña123" not in caplog.text


def test_choice_id_ida_y_vuelta():
    assert encode_choice_id("done", 42) == "done:42"
    assert decode_choice_id("done:42") == ("done", ["42"])
    assert decode_choice_id("cancel") == ("cancel", [])


def test_choice_id_demasiado_largo():
    with pytest.raises(ValueError):
        encode_choice_id("x" * (MAX_CHOICE_ID_BYTES + 1))
