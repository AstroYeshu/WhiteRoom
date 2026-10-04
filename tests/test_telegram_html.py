"""Corte 1: el canal de Telegram envía HTML y, si Telegram no puede leerlo, reintenta UNA vez en
texto plano antes de tratarlo como un error permanente (un recordatorio no se pierde por formato).
"""

import asyncio
import logging

import pytest
from telegram import error as tg_error

from asistente import formato as fmt
from asistente.channels import telegram as tg
from asistente.channels.base import Choice, PermanentChannelError, TransientChannelError
from asistente.channels.console import ConsoleChannel
from tests.htmlcheck import assert_valid_telegram_html

CANT_PARSE = tg_error.BadRequest("Bad Request: can't parse entities: Can't find end of the entity")


@pytest.fixture
def channel() -> tg.TelegramChannel:
    return tg.TelegramChannel("123456:token-falso", allowed_user_id=1)


class Wire:
    """Reemplaza `send_message` / `edit_message_text` del bot y anota cada llamada."""

    def __init__(self, channel, monkeypatch, behavior=lambda call, kwargs: None) -> None:
        self.sends: list[dict] = []
        self.edits: list[dict] = []
        self.behavior = behavior
        bot_type = type(channel._application.bot)

        async def send_message(bot, **kwargs):
            self.sends.append(kwargs)
            return self.behavior(len(self.sends), kwargs)

        async def edit_message_text(bot, **kwargs):
            self.edits.append(kwargs)
            return self.behavior(len(self.edits), kwargs)

        monkeypatch.setattr(bot_type, "send_message", send_message)
        monkeypatch.setattr(bot_type, "edit_message_text", edit_message_text)


def fail_first_with(error):
    def behavior(call, kwargs):
        if call == 1:
            raise error

    return behavior


def run(coroutine):
    return asyncio.run(coroutine)


# --- HTML por defecto ----------------------------------------------------------------------------


def test_un_texto_plano_se_escapa_y_se_envia_como_html(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    run(channel.send_text("1", "comprar <leche> & pan"))
    assert wire.sends[0]["text"] == "comprar &lt;leche&gt; &amp; pan"
    assert wire.sends[0]["parse_mode"] == "HTML"


def test_un_html_de_format_py_se_envia_tal_cual(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    run(channel.send_text("1", fmt.bold("llevar <tarea>")))
    assert wire.sends[0]["text"] == "<b>llevar &lt;tarea&gt;</b>"
    assert wire.sends[0]["parse_mode"] == "HTML"


def test_send_choices_y_edit_text_tambien_usan_html(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    run(channel.send_choices("1", fmt.bold("x"), [Choice("a:1", "A")]))
    run(channel.edit_text("1", "77", fmt.bold("y")))
    assert wire.sends[0]["parse_mode"] == "HTML" and wire.edits[0]["parse_mode"] == "HTML"


# --- Distribución de botones ---------------------------------------------------------------------


def rows_of(call: dict) -> list[list[str]]:
    return [[button.text for button in row] for row in call["reply_markup"].inline_keyboard]


def test_sin_distribucion_cada_boton_va_en_su_fila(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    run(channel.send_choices("1", "x", [Choice("a:1", "A"), Choice("b:1", "B")]))
    assert rows_of(wire.sends[0]) == [["A"], ["B"]]


def test_la_distribucion_agrupa_los_botones_en_filas(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    choices = [Choice(f"c:{n}", f"B{n}") for n in range(5)]
    run(channel.send_choices("1", "x", choices, layout=(2, 2, 1)))
    assert rows_of(wire.sends[0]) == [["B0", "B1"], ["B2", "B3"], ["B4"]]
    assert wire.sends[0]["reply_markup"].inline_keyboard[0][1].callback_data == "c:1"


def test_una_distribucion_que_no_suma_es_un_error_de_programacion(channel, monkeypatch):
    Wire(channel, monkeypatch)
    with pytest.raises(ValueError):
        run(channel.send_choices("1", "x", [Choice("a:1", "A")], layout=(2,)))


# --- Reintento en texto plano --------------------------------------------------------------------


def test_si_telegram_no_puede_leer_el_html_reintenta_una_vez_en_texto_plano(channel, monkeypatch):
    wire = Wire(channel, monkeypatch, fail_first_with(CANT_PARSE))
    run(channel.send_choices("1", fmt.bold("a <b> c"), [Choice("a:1", "A")], layout=(1,)))
    assert len(wire.sends) == 2
    assert wire.sends[0]["parse_mode"] == "HTML"
    assert wire.sends[1].get("parse_mode") is None
    assert wire.sends[1]["text"] == "a <b> c"  # sin etiquetas y con el texto original
    assert wire.sends[1]["reply_markup"] is not None  # los botones no se pierden


def test_si_tambien_falla_en_texto_plano_es_permanente_y_no_hay_tercer_intento(
    channel, monkeypatch
):
    wire = Wire(channel, monkeypatch, lambda call, kwargs: (_ for _ in ()).throw(CANT_PARSE))
    with pytest.raises(PermanentChannelError) as raised:
        run(channel.send_text("1", fmt.bold("x")))
    assert raised.value.reason == "bad_request:cant_parse_entities"
    assert len(wire.sends) == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (tg_error.BadRequest("Chat not found"), PermanentChannelError),
        (tg_error.Forbidden("Forbidden: bot was blocked by the user"), PermanentChannelError),
        (tg_error.TimedOut(), TransientChannelError),
        (tg_error.NetworkError("Bad Gateway"), TransientChannelError),
    ],
)
def test_otros_errores_no_reintentan_en_texto_plano(channel, monkeypatch, error, expected):
    wire = Wire(channel, monkeypatch, lambda call, kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(expected):
        run(channel.send_text("1", fmt.bold("x")))
    assert len(wire.sends) == 1


def test_el_reintento_en_texto_plano_no_registra_el_texto(channel, monkeypatch, caplog):
    Wire(channel, monkeypatch, fail_first_with(CANT_PARSE))
    with caplog.at_level(logging.DEBUG):
        run(channel.send_text("1", fmt.bold("secretoprivado")))
    assert "secretoprivado" not in caplog.text
    assert "texto plano" in caplog.text


def test_editar_tambien_reintenta_en_texto_plano(channel, monkeypatch):
    wire = Wire(channel, monkeypatch, fail_first_with(CANT_PARSE))
    run(channel.edit_text("1", "77", fmt.state_line("Hecho", "a <b> c")))
    assert len(wire.edits) == 2
    assert wire.edits[1].get("parse_mode") is None
    assert wire.edits[1]["text"] == "Hecho · a <b> c"


def test_editar_con_doble_fallo_no_lanza(channel, monkeypatch):
    Wire(channel, monkeypatch, lambda call, kwargs: (_ for _ in ()).throw(CANT_PARSE))
    run(channel.edit_text("1", "77", fmt.bold("x")))  # cosmético: no propaga


# --- Textos hostiles: lo que sale siempre es HTML válido -----------------------------------------

HOSTILE = ["< > & * _ [ ] ` \" '", "<b>x</b> <i>", "a&b&amp;c", "</code>", "`<code>`", "<<>>"]


@pytest.mark.parametrize("text", HOSTILE)
def test_ningun_texto_hostil_produce_html_invalido(channel, monkeypatch, text):
    wire = Wire(channel, monkeypatch)
    run(channel.send_text("1", text))  # texto plano del usuario
    run(channel.send_text("1", fmt.reminder_notice(text, text, True)))
    run(channel.send_text("1", fmt.state_line("Hecho", text, text)))
    run(channel.edit_text("1", "77", fmt.aviso(text)))
    for call in [*wire.sends, *wire.edits]:
        assert_valid_telegram_html(call["text"])


# --- La consola quita las etiquetas --------------------------------------------------------------


def test_la_consola_muestra_texto_sin_etiquetas():
    printed: list[str] = []
    console = ConsoleChannel("1", output_fn=printed.append)
    run(console.send_text("1", fmt.reminder_notice("a <b> & c", "iglesia", True)))
    run(console.send_choices("1", fmt.bold("Elige"), [Choice("a:1", "A"), Choice("b:1", "B")]))
    run(console.edit_text("1", "77", fmt.state_line("Hecho", "x")))
    assert printed[0] == "a <b> & c\n\nRecordatorio · iglesia (retrasado)"
    assert printed[1:4] == ["Elige", "  1) A", "  2) B"]
    assert printed[4] == "[editado] Hecho · x"


# --- Corte 2: referencias de mensaje y edición con botones ---------------------------------------


def message(message_id: int):
    from types import SimpleNamespace

    return SimpleNamespace(message_id=message_id)


def test_enviar_devuelve_la_referencia_del_mensaje(channel, monkeypatch):
    Wire(channel, monkeypatch, lambda call, kwargs: message(500 + call))
    assert run(channel.send_text("1", "a")) == "501"
    assert run(channel.send_choices("1", "b", [Choice("a:1", "A")])) == "502"


def test_enviar_sin_referencia_devuelve_none(channel, monkeypatch):
    Wire(channel, monkeypatch)  # la red falsa no devuelve nada
    assert run(channel.send_text("1", "a")) is None


def test_editar_con_botones_los_pone_con_su_distribucion(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    choices = [Choice(f"c:{n}", f"B{n}") for n in range(3)]
    assert run(channel.edit_text("1", "77", fmt.bold("x"), choices, (2, 1))) is True
    assert rows_of(wire.edits[0]) == [["B0", "B1"], ["B2"]]
    assert wire.edits[0]["parse_mode"] == "HTML"


def test_editar_sin_botones_no_manda_teclado_y_devuelve_true(channel, monkeypatch):
    wire = Wire(channel, monkeypatch)
    assert run(channel.edit_text("1", "77", fmt.bold("x"))) is True
    assert wire.edits[0].get("reply_markup") is None


def test_editar_con_el_mismo_texto_cuenta_como_exito(channel, monkeypatch):
    error = tg_error.BadRequest("Message is not modified: specified new message content")
    Wire(channel, monkeypatch, lambda call, kwargs: (_ for _ in ()).throw(error))
    assert run(channel.edit_text("1", "77", "igual")) is True


@pytest.mark.parametrize(
    "error",
    [
        tg_error.BadRequest("Message to edit not found"),
        tg_error.Forbidden("Forbidden: bot was blocked by the user"),
        tg_error.TimedOut(),
        tg_error.NetworkError("Bad Gateway"),
    ],
)
def test_si_no_se_pudo_editar_devuelve_false_y_no_lanza(channel, monkeypatch, error):
    Wire(channel, monkeypatch, lambda call, kwargs: (_ for _ in ()).throw(error))
    assert run(channel.edit_text("1", "77", "x", [Choice("a:1", "A")])) is False


def test_el_reintento_en_texto_plano_al_editar_conserva_los_botones(channel, monkeypatch):
    wire = Wire(channel, monkeypatch, fail_first_with(CANT_PARSE))
    assert run(channel.edit_text("1", "77", fmt.bold("a <b>"), [Choice("a:1", "A")], (1,))) is True
    assert len(wire.edits) == 2
    assert wire.edits[1].get("parse_mode") is None
    assert rows_of(wire.edits[1]) == [["A"]]


def test_la_consola_edita_mostrando_los_botones_y_devuelve_true():
    printed: list[str] = []
    console = ConsoleChannel("1", output_fn=printed.append)
    ok = run(
        console.edit_text("1", "m1", fmt.bold("Elige"), [Choice("a:1", "A"), Choice("b:1", "B")])
    )
    assert ok is True
    assert printed == ["[editado] Elige", "  1) A", "  2) B"]
    assert run(console.send_text("1", "x")) is None  # la consola no tiene referencias
