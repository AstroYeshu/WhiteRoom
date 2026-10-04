"""Corte 1: textos hostiles (< > & * _ [ ] ` y comillas) en recordatorios, tareas y notas, de
punta a punta con el canal REAL de Telegram (parcheado en la red). Todo lo que sale debe ser HTML
válido y lo guardado debe ser EXACTAMENTE lo que escribió el usuario.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from asistente import formato as fmt
from asistente.bot import handlers
from asistente.bot.conversation import Conversation
from asistente.channels import telegram as tg
from asistente.channels.base import IncomingChoice, IncomingMessage
from asistente.core import areas, notes, reminders, tasks
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import local_to_utc
from tests.botkit import OWNER, TZ
from tests.htmlcheck import assert_valid_telegram_html

HOSTILE = "<b>x</b> & \"q\" 's' *a* _b_ [c](d) `e` > <i"
_runner = asyncio.Runner()


def run(coroutine):
    return _runner.run(coroutine)


def teardown_module(module):
    _runner.close()


class TgBot:
    """Maneja los manejadores reales con `TelegramChannel`; solo la red es falsa."""

    def __init__(self, conn, clock, monkeypatch) -> None:
        self.conn, self.clock = conn, clock
        self.channel = tg.TelegramChannel("123456:token-falso", allowed_user_id=OWNER)
        self.conversation = Conversation()
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        bot_type = type(self.channel._application.bot)

        async def send_message(bot, **kwargs):
            self.sent.append(kwargs)

        async def edit_message_text(bot, **kwargs):
            self.edited.append(kwargs)

        monkeypatch.setattr(bot_type, "send_message", send_message)
        monkeypatch.setattr(bot_type, "edit_message_text", edit_message_text)
        self.engine = ReminderEngine(conn, self.channel, str(OWNER), TZ, clock)

    def say(self, text: str) -> None:
        event = IncomingMessage("telegram", str(OWNER), text)
        run(
            handlers.handle_message(
                event, self.channel, OWNER, self.conn, self.clock, TZ, self.conversation
            )
        )

    def tap(self, label: str) -> None:
        for call in reversed(self.sent):
            markup = call.get("reply_markup")
            if markup is None:
                continue
            for row in markup.inline_keyboard:
                for button in row:
                    if button.text == label or label in button.text:
                        event = IncomingChoice("telegram", str(OWNER), button.callback_data, "77")
                        run(
                            handlers.handle_choice(
                                event,
                                self.channel,
                                OWNER,
                                self.conn,
                                self.clock,
                                TZ,
                                self.conversation,
                            )
                        )
                        return
            break
        raise LookupError(label)

    def tick(self) -> None:
        run(self.engine.tick())

    def everything(self) -> list[str]:
        return [call["text"] for call in [*self.sent, *self.edited]]

    def assert_all_valid(self) -> None:
        assert self.everything(), "no se envió nada"
        for call in [*self.sent, *self.edited]:
            assert call["parse_mode"] == "HTML"
            assert_valid_telegram_html(call["text"])


@pytest.fixture
def bot(conn, clock, monkeypatch) -> TgBot:
    return TgBot(conn, clock, monkeypatch)


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


def test_un_recordatorio_hostil_llega_como_html_valido_y_sin_alterar(bot, conn, clock):
    area = areas.create_area(conn, "A<b>&", "desc", clock)
    reminders.create_reminder(conn, HOSTILE, clock() + timedelta(minutes=1), clock, area_id=area.id)
    clock.advance(minutes=5)
    bot.tick()
    bot.assert_all_valid()
    assert bot.sent[0]["text"].startswith("<b>")
    assert fmt.plain(fmt.Html(bot.sent[0]["text"])).startswith(HOSTILE)
    [row] = conn.execute("SELECT text, status FROM reminders").fetchall()
    assert (row["text"], row["status"]) == (HOSTILE, "sent")  # lo guardado no se tocó


def test_una_tarea_hostil_por_la_bandeja(bot, conn):
    bot.say(HOSTILE)
    bot.tap("Tarea")
    bot.tap("Sin área")
    bot.assert_all_valid()
    [row] = conn.execute("SELECT title, source_text FROM tasks").fetchall()
    assert (row["title"], row["source_text"]) == (HOSTILE, HOSTILE)


def test_una_nota_hostil(bot, conn):
    bot.say(f"/nota {HOSTILE}")
    bot.tap("Sin área")
    bot.assert_all_valid()
    assert notes.list_notes(conn)[0].text == HOSTILE


def test_un_recordar_hostil_hasta_guardar(bot, conn):
    bot.say(f"/recordar mañana 8am {HOSTILE}")
    bot.tap("Sin área")
    bot.tap("Guardar")
    bot.assert_all_valid()
    assert reminders.list_pending(conn)[0].text.endswith("<i")


def test_comandos_de_lectura_con_contenido_hostil(bot, conn, clock):
    area = areas.create_area(conn, "A<b>&", "", clock)
    task = tasks.create_task(conn, HOSTILE, clock, area_id=area.id)
    with conn:
        conn.execute(
            "UPDATE tasks SET due_at_utc = ? WHERE id = ?",
            (local("2026-10-03 17:00").isoformat(timespec="seconds"), task.id),
        )
    reminders.create_reminder(conn, HOSTILE, local("2026-10-03 18:00"), clock, area_id=area.id)
    for command in ("/hoy", "/pendientes", "/recordatorios", "/areas", f"/hoy {HOSTILE}"):
        bot.say(command)
    bot.tap("Hecha")
    bot.assert_all_valid()


def test_nuevaarea_hostil(bot, conn):
    bot.say(f"/nuevaarea {HOSTILE[:30]}")
    bot.say(HOSTILE)
    bot.assert_all_valid()


def test_el_fallback_de_texto_plano_no_pierde_el_aviso(conn, clock, monkeypatch):
    """Si Telegram rechazara el formato, el aviso sale igual (en plano) y queda enviado."""
    from telegram import error as tg_error

    channel = tg.TelegramChannel("123456:token-falso", allowed_user_id=OWNER)
    calls: list[dict] = []

    async def send_message(bot, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise tg_error.BadRequest("Can't parse entities: unsupported start tag")

    monkeypatch.setattr(type(channel._application.bot), "send_message", send_message)
    created = reminders.create_reminder(conn, HOSTILE, clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    run(ReminderEngine(conn, channel, str(OWNER), TZ, clock).tick())
    assert len(calls) == 2 and calls[1].get("parse_mode") is None
    assert calls[1]["text"].startswith(HOSTILE)
    assert reminders.get_reminder(conn, created.id).status == "sent"
    assert reminders.get_reminder(conn, created.id).stop_reason is None
