"""Bloque 6, punto 3, lado del canal: responder a la pulsación y editar el mensaje.

- El dueño SIEMPRE recibe `answer_callback_query` (se quita el relojito); un extraño, nada.
- Editar con el mismo texto ("message is not modified") no es un error.
- Un fallo al editar o al responder no impide la acción ni propaga el error.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from telegram import error as tg_error

from asistente.channels import telegram as tg
from asistente.channels.base import Choice, IncomingChoice
from asistente.channels.console import ConsoleChannel


@pytest.fixture
def channel() -> tg.TelegramChannel:
    return tg.TelegramChannel("123456:token-falso", allowed_user_id=1)


def patch_edit(channel, monkeypatch, behavior) -> list[dict]:
    calls: list[dict] = []

    async def edit_message_text(self, **kwargs):
        calls.append(kwargs)
        return behavior(kwargs)

    monkeypatch.setattr(type(channel._application.bot), "edit_message_text", edit_message_text)
    return calls


def raise_(error: Exception):
    def behavior(kwargs):
        raise error

    return behavior


# --- edit_text --------------------------------------------------------------------------------


def test_edit_text_edita_el_mensaje_y_quita_el_teclado(channel, monkeypatch):
    calls = patch_edit(channel, monkeypatch, lambda kwargs: None)
    asyncio.run(channel.edit_text("1", "77", "Hecho: x"))
    assert len(calls) == 1
    assert calls[0]["chat_id"] == 1 and calls[0]["message_id"] == 77
    assert calls[0]["text"] == "Hecho: x"
    assert calls[0].get("reply_markup") is None  # sin teclado: Telegram lo quita


def test_editar_con_el_mismo_texto_no_lanza_error(channel, monkeypatch):
    patch_edit(
        channel,
        monkeypatch,
        raise_(
            tg_error.BadRequest(
                "Message is not modified: specified new message content and reply markup are "
                "exactly the same as a current content and reply markup of the message"
            )
        ),
    )
    asyncio.run(channel.edit_text("1", "77", "igual"))  # no debe lanzar


@pytest.mark.parametrize(
    "error",
    [
        tg_error.BadRequest("Message to edit not found"),
        tg_error.Forbidden("Forbidden: bot was blocked by the user"),
        tg_error.TimedOut(),
        tg_error.NetworkError("Bad Gateway"),
        tg_error.RetryAfter(3),
    ],
)
def test_un_fallo_al_editar_se_registra_sin_texto_y_no_lanza(channel, monkeypatch, caplog, error):
    """Editar es cosmético: la acción (hecho, posponer) ya se hizo."""
    patch_edit(channel, monkeypatch, raise_(error))
    with caplog.at_level(logging.DEBUG):
        asyncio.run(channel.edit_text("1", "77", "secreto-médico"))
    assert type(error).__name__ in caplog.text
    assert "secreto-médico" not in caplog.text


# --- Pulsación del botón -----------------------------------------------------------------------


def run_callback(
    channel, monkeypatch, user_id: int, answer, message_id: int | None = 55, toast=None, fail=None
):
    captured: dict = {}
    monkeypatch.setattr(
        channel._application,
        "add_handler",
        lambda h, *a, **k: captured.setdefault("h", []).append(h),
    )
    monkeypatch.setattr(channel._application, "add_error_handler", lambda cb: None)
    monkeypatch.setattr(channel._application, "run_polling", lambda: None)
    received: list[IncomingChoice] = []

    async def record(event):
        received.append(event)
        if fail is not None:
            raise fail
        return toast  # el aviso breve con que el manejador responde a la pulsación

    async def no_tick() -> int:
        return 0

    channel.run_polling(record, record, no_tick)
    _, callback_handler = captured["h"]
    message = None if message_id is None else SimpleNamespace(message_id=message_id)
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        callback_query=SimpleNamespace(data="rem_done:3", answer=answer, message=message),
    )
    try:
        asyncio.run(callback_handler.callback(update, None))
    except RuntimeError:
        if fail is None:
            raise
    return received


def test_el_dueno_recibe_answer_y_la_referencia_del_mensaje(channel, monkeypatch):
    answered: list[bool] = []

    async def answer() -> None:
        answered.append(True)

    received = run_callback(channel, monkeypatch, 1, answer)
    assert answered == [True]
    assert received == [IncomingChoice("telegram", "1", "rem_done:3", "55")]


def test_un_extrano_no_recibe_answer_ni_se_procesa(channel, monkeypatch):
    answered: list[bool] = []

    async def answer() -> None:
        answered.append(True)

    assert run_callback(channel, monkeypatch, 999, answer) == []
    assert answered == []


def test_si_answer_falla_la_accion_se_procesa_igual(channel, monkeypatch, caplog):
    async def answer() -> None:
        raise tg_error.TimedOut()

    with caplog.at_level(logging.DEBUG):
        received = run_callback(channel, monkeypatch, 1, answer)
    assert len(received) == 1  # la pulsación del dueño no se pierde por un fallo cosmético
    assert "TimedOut" in caplog.text


def test_un_boton_sin_mensaje_asociado_llega_sin_referencia(channel, monkeypatch):
    async def answer() -> None:
        return None

    received = run_callback(channel, monkeypatch, 1, answer, message_id=None)
    assert received[0].message_ref is None


# --- Consola ----------------------------------------------------------------------------------


def test_la_consola_muestra_el_texto_editado():
    output: list[str] = []
    console = ConsoleChannel("1", input_fn=lambda p: "", output_fn=output.append)
    asyncio.run(console.edit_text("1", "ignorado", "Hecho: x"))
    assert output == ["[editado] Hecho: x"]


# --- Aviso breve (answer_callback_query con texto) -------------------------------------------


def test_el_aviso_breve_del_manejador_se_muestra_al_responder_la_pulsacion(channel, monkeypatch):
    answers: list[dict] = []

    async def answer(**kwargs) -> None:
        answers.append(kwargs)

    received = run_callback(channel, monkeypatch, 1, answer, toast="Esa opción ya no aplica")
    assert answers == [{"text": "Esa opción ya no aplica"}]
    assert len(received) == 1


def test_sin_aviso_se_responde_la_pulsacion_sin_texto(channel, monkeypatch):
    answers: list[dict] = []

    async def answer(**kwargs) -> None:
        answers.append(kwargs)

    run_callback(channel, monkeypatch, 1, answer)
    assert answers == [{}]


def test_si_el_manejador_falla_la_pulsacion_se_responde_igual(channel, monkeypatch):
    answers: list[dict] = []

    async def answer(**kwargs) -> None:
        answers.append(kwargs)

    run_callback(channel, monkeypatch, 1, answer, fail=RuntimeError("falla"))
    assert answers == [{}]  # el relojito del botón se quita aunque el manejador falle


def test_la_consola_muestra_el_aviso_breve_entre_parentesis():
    output: list[str] = []
    lines = iter(["1", "/salir"])
    console = ConsoleChannel("1", input_fn=lambda p: next(lines), output_fn=output.append)

    async def scenario() -> None:
        await console.send_choices("1", "Elige", [Choice("a:1", "A")])

        async def on_choice(event):
            return "Esa opción ya no aplica"

        async def on_message(event):
            return None

        await console._read_loop(on_message, on_choice)

    asyncio.run(scenario())
    assert "(Esa opción ya no aplica)" in output
