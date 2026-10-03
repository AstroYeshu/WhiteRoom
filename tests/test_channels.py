import asyncio
from types import SimpleNamespace

from asistente.channels.base import Choice, IncomingChoice, IncomingMessage
from asistente.channels.console import ConsoleChannel
from asistente.channels.telegram import build_keyboard

CHOICES = [Choice("done:42", "Hecho"), Choice("snooze:42", "+10 min")]


def make_console(lines: list[str]) -> tuple[ConsoleChannel, list[str]]:
    output: list[str] = []
    feed = iter(lines)

    def fake_input(prompt: str) -> str:
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    return ConsoleChannel("1", input_fn=fake_input, output_fn=output.append), output


def test_consola_muestra_opciones_como_lista_numerada():
    channel, output = make_console([])
    asyncio.run(channel.send_choices("1", "¿Qué hago?", CHOICES))
    assert output == ["¿Qué hago?", "  1) Hecho", "  2) +10 min"]


def test_consola_etiqueta_los_mensajes_proactivos():
    channel, output = make_console([])
    asyncio.run(channel.send_text("1", "hola", kind="reminder"))
    assert output == ["[reminder] hola"]


def test_consola_convierte_entradas_y_numeros_en_elecciones():
    messages: list[IncomingMessage] = []
    picked: list[IncomingChoice] = []

    async def on_message(msg: IncomingMessage) -> None:
        messages.append(msg)
        if msg.text == "/ayuda":
            await channel.send_choices("1", "elige", CHOICES)

    async def on_choice(choice: IncomingChoice) -> None:
        picked.append(choice)

    channel, _ = make_console(["/ayuda", "2", "2", "", "/salir", "nunca llega"])
    asyncio.run(channel.serve(on_message, on_choice))

    # El primer "2" elige (hay opciones pendientes); el segundo ya es texto normal.
    assert picked == [IncomingChoice("console", "1", "snooze:42")]
    assert [m.text for m in messages] == ["/ayuda", "2"]


def test_consola_termina_con_fin_de_entrada():
    channel, _ = make_console([])

    async def nothing(_event) -> None:
        raise AssertionError("no debía llegar nada")

    asyncio.run(channel.serve(nothing, nothing))


def test_teclado_de_telegram_lleva_el_id_como_callback_data():
    keyboard = build_keyboard(CHOICES)
    buttons = [row[0] for row in keyboard.inline_keyboard]
    assert [(b.text, b.callback_data) for b in buttons] == [
        ("Hecho", "done:42"),
        ("+10 min", "snooze:42"),
    ]


def test_telegram_ignora_en_silencio_a_usuarios_no_autorizados(monkeypatch):
    """Se arma el canal sin red y se simula una actualización de un extraño."""
    from asistente.channels import telegram as tg

    channel = tg.TelegramChannel("123456:token-falso", allowed_user_id=1)
    captured = {}

    def fake_add_handler(handler, *args, **kwargs):
        captured.setdefault("handlers", []).append(handler)

    monkeypatch.setattr(channel._application, "add_handler", fake_add_handler)
    monkeypatch.setattr(channel._application, "add_error_handler", lambda cb: None)
    monkeypatch.setattr(channel._application, "run_polling", lambda: None)

    received: list[object] = []

    async def record(event) -> None:
        received.append(event)

    channel.run_polling(record, record)
    text_handler, callback_handler = captured["handlers"]

    answered: list[bool] = []

    async def answer() -> None:
        answered.append(True)

    def update(user_id: int):
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(text="hola"),
            callback_query=SimpleNamespace(data="done:1", answer=answer),
        )

    asyncio.run(text_handler.callback(update(999), None))
    asyncio.run(callback_handler.callback(update(999), None))
    assert received == []
    assert answered == []  # ni siquiera se responde al botón

    asyncio.run(text_handler.callback(update(1), None))
    asyncio.run(callback_handler.callback(update(1), None))
    assert received == [
        IncomingMessage("telegram", "1", "hola"),
        IncomingChoice("telegram", "1", "done:1"),
    ]
    assert answered == [True]
