"""M1: el canal de Telegram traduce los errores de la librería a los dos grupos del motor.

- Salud del canal (red, timeout, límite de envíos, 5xx): `TransientChannelError`.
- Culpa del mensaje o del chat (BadRequest, bot bloqueado...): `PermanentChannelError`.
"""

import asyncio
import logging
from datetime import timedelta

import pytest
from telegram import error as tg_error

from asistente.channels import telegram as tg
from asistente.channels.base import (
    Choice,
    PermanentChannelError,
    TransientChannelError,
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
            "bad_request:can_t_parse_entities_unexpected_end",
        ),
        (
            tg_error.Conflict("terminated by other getUpdates request"),
            "bad_request:terminated_by_other_getupdates_request",
        ),
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


def test_la_razon_de_un_badrequest_largo_se_acota(channel, monkeypatch):
    raising(channel, monkeypatch, tg_error.BadRequest("x" * 500))
    with pytest.raises(PermanentChannelError) as caught:
        send(channel, "text")
    assert len(caught.value.reason) <= len("bad_request:") + tg.MAX_REASON_SLUG


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
