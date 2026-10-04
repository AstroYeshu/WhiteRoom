"""M1: el canal de Telegram traduce los errores de la librería a los dos grupos del motor.

- Salud del canal (red, timeout, límite de envíos, 5xx): `TransientChannelError`.
- Culpa del mensaje o del chat (BadRequest, bot bloqueado...): `PermanentChannelError`.
"""

import asyncio
import logging
import re
from datetime import timedelta

import pytest
from telegram import error as tg_error

from asistente.channels import telegram as tg
from asistente.channels.base import (
    Choice,
    PermanentChannelError,
    TransientChannelError,
    UnclassifiedChannelError,
)

CHOICES = [Choice("rem_done:1", "Hecho")]


@pytest.fixture
def channel() -> tg.TelegramChannel:
    return tg.TelegramChannel("123456:token-falso", allowed_user_id=1)


def raising(channel: tg.TelegramChannel, monkeypatch, error: Exception) -> None:
    async def send_message(self, *args, **kwargs):
        raise error

    # ExtBot no admite reemplazar métodos en la instancia: se parchea la clase.
    monkeypatch.setattr(type(channel._application.bot), "send_message", send_message)


def send(channel: tg.TelegramChannel, how: str) -> None:
    if how == "text":
        asyncio.run(channel.send_text("1", "hola"))
    else:
        asyncio.run(channel.send_choices("1", "hola", CHOICES))


@pytest.mark.parametrize("how", ["text", "choices"])
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (tg_error.Forbidden("Forbidden: bot was blocked by the user"), "bot_blocked"),
        (tg_error.Forbidden("Forbidden: user is deactivated"), "bot_blocked"),
        (tg_error.BadRequest("Chat not found"), "chat_not_found"),
        (tg_error.BadRequest("Message is too long"), "message_too_long"),
        (
            tg_error.BadRequest("Can't parse entities: unexpected end"),
            "bad_request:cant_parse_entities",
        ),
        (tg_error.BadRequest("Message text is empty"), "bad_request:empty_text"),
        (tg_error.BadRequest("BUTTON_DATA_INVALID"), "bad_request:button_data_invalid"),
        (tg_error.BadRequest("Wrong file identifier"), "bad_request:other"),
    ],
)
def test_culpa_del_mensaje_o_del_chat_es_permanente(channel, monkeypatch, how, error, reason):
    raising(channel, monkeypatch, error)
    with pytest.raises(PermanentChannelError) as caught:
        send(channel, how)
    assert caught.value.reason == reason


def test_badrequest_se_traduce_antes_que_networkerror(channel, monkeypatch):
    """En la librería BadRequest hereda de NetworkError: no debe contar como caída del canal."""
    assert issubclass(tg_error.BadRequest, tg_error.NetworkError)
    raising(channel, monkeypatch, tg_error.BadRequest("Wrong file identifier"))
    with pytest.raises(PermanentChannelError):
        send(channel, "text")


@pytest.mark.parametrize(
    "message",
    [
        "Hola 😀 secreto-médico, ¿qué pasó? https://evil.example/x?token=abc#frag",
        "x" * 500,
        "ñandú\nlínea 2\t\x00",
        "",
    ],
)
def test_el_codigo_de_un_badrequest_desconocido_no_lleva_texto_arbitrario(
    channel, monkeypatch, message
):
    raising(channel, monkeypatch, tg_error.BadRequest(message))
    with pytest.raises(PermanentChannelError) as caught:
        send(channel, "text")
    assert caught.value.reason == "bad_request:other"


@pytest.mark.parametrize(
    "error",
    [
        tg_error.BadRequest("Hola 😀 https://evil.example/x?token=abc"),
        tg_error.BadRequest("Can't parse entities: ñandú 😀"),
        tg_error.BadRequest("Message is too long"),
        tg_error.BadRequest("Chat not found"),
        tg_error.Forbidden("Forbidden: bot was blocked by the user"),
    ],
)
def test_todo_codigo_permanente_es_estable_y_limpio(channel, monkeypatch, error):
    raising(channel, monkeypatch, error)
    with pytest.raises(PermanentChannelError) as caught:
        send(channel, "text")
    assert re.fullmatch(r"[a-z0-9_]{1,40}(:[a-z0-9_]{1,40})?", caught.value.reason)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (tg_error.Conflict("terminated by other getUpdates request"), "telegram_error:Conflict"),
        (tg_error.ChatMigrated(-100123), "telegram_error:ChatMigrated"),
        (tg_error.TelegramError("algo con 😀 y https://x.y"), "telegram_error:TelegramError"),
    ],
)
def test_error_de_telegram_sin_categoria_lo_decide_el_motor_por_evidencia(
    channel, monkeypatch, error, reason
):
    """Ni permanente ni transitorio: el motor prueba con los demás antes de culpar a la fila."""
    raising(channel, monkeypatch, error)
    with pytest.raises(UnclassifiedChannelError) as caught:
        send(channel, "text")
    assert not isinstance(caught.value, PermanentChannelError | TransientChannelError)
    assert caught.value.reason == reason


@pytest.mark.parametrize("how", ["text", "choices"])
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (tg_error.TimedOut(), "timeout"),
        (tg_error.NetworkError("Bad Gateway"), "network"),
        (tg_error.NetworkError("Service Unavailable (503)"), "network"),
        (tg_error.InvalidToken(), "invalid_token"),
    ],
)
def test_salud_del_canal_es_transitoria(channel, monkeypatch, how, error, reason):
    raising(channel, monkeypatch, error)
    with pytest.raises(TransientChannelError) as caught:
        send(channel, how)
    assert caught.value.reason == reason
    assert caught.value.retry_after is None


def test_retry_after_lleva_la_espera_indicada_en_segundos(channel, monkeypatch):
    raising(channel, monkeypatch, tg_error.RetryAfter(17))
    with pytest.raises(TransientChannelError) as caught:
        send(channel, "text")
    assert caught.value.reason == "rate_limited"
    assert caught.value.retry_after == 17


def test_retry_after_acepta_timedelta(channel, monkeypatch):
    raising(channel, monkeypatch, tg_error.RetryAfter(timedelta(seconds=42)))
    with pytest.raises(TransientChannelError) as caught:
        send(channel, "text")
    assert caught.value.retry_after == 42


def test_una_excepcion_que_no_es_de_telegram_no_se_traduce(channel, monkeypatch):
    """La clasifica el motor (transitoria, pero aislable por fila)."""
    raising(channel, monkeypatch, RuntimeError("algo raro"))
    with pytest.raises(RuntimeError):
        send(channel, "text")


def test_el_texto_del_usuario_nunca_va_al_log(channel, monkeypatch, caplog):
    raising(channel, monkeypatch, tg_error.BadRequest("Chat not found"))
    with caplog.at_level(logging.DEBUG), pytest.raises(PermanentChannelError):
        asyncio.run(channel.send_text("1", "secreto-médico"))
    assert "secreto-médico" not in caplog.text


def test_el_ayudante_de_espera_acepta_entero_y_timedelta():
    assert tg.seconds_from(17) == 17
    assert tg.seconds_from(timedelta(minutes=2)) == 120
    assert tg.seconds_from(2.5) == 2.5


def test_el_traductor_no_silencia_los_avisos_de_la_libreria():
    """Los avisos de obsolescencia de `retry_after` se ven hasta que se actualice la librería."""
    import inspect

    assert "catch_warnings" not in inspect.getsource(tg)
    assert "simplefilter" not in inspect.getsource(tg)
