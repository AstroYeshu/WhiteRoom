"""Bloque 6, punto 3: botones del recordatorio (`rem_done`, `rem_snooze`, `rem_tomorrow`).

Reloj inicial: sábado 2026-10-03 15:30 en México. El mensaje del botón se EDITA (texto nuevo y sin
teclado); pulsar dos veces o pulsar un botón viejo no da error.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from asistente.bot import handlers
from asistente.bot.conversation import Conversation
from asistente.channels.base import IncomingChoice
from asistente.core import reminders
from asistente.timeutil import from_utc_iso, local_to_utc
from tests.fakes import FakeChannel

TZ = "America/Mexico_City"
OWNER = 12345
REF = "77"  # id del mensaje que lleva los botones


@pytest.fixture
def channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def sent_reminder(conn, clock) -> reminders.Reminder:
    """Un recordatorio ya avisado (`sent`), que es cuando se ven los botones."""
    created = reminders.create_reminder(conn, "llevar tarea", clock() + timedelta(minutes=1), clock)
    clock.advance(minutes=1)
    with conn:
        conn.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (created.id,))
    return created


def press(conn, clock, channel, choice_id: str, user: int = OWNER, ref: str | None = REF) -> None:
    event = IncomingChoice("fake", str(user), choice_id, ref)
    asyncio.run(handlers.handle_choice(event, channel, OWNER, conn, clock, TZ, Conversation()))


def row(conn, reminder_id: int) -> reminders.Reminder:
    stored = reminders.get_reminder(conn, reminder_id)
    assert stored is not None
    return stored


def edited(channel: FakeChannel) -> list[str]:
    return [text for _, _, text in channel.edits]


# --- Hecho ---------------------------------------------------------------------------------


def test_hecho_marca_el_recordatorio_y_edita_el_mensaje_sin_teclado(
    conn, clock, channel, sent_reminder
):
    press(conn, clock, channel, f"rem_done:{sent_reminder.id}")
    assert row(conn, sent_reminder.id).status == "done"
    assert channel.edits == [(str(OWNER), REF, "<b>Hecho</b> · llevar tarea")]
    assert not channel.sent_anything  # se edita el mensaje, no se manda otro


def test_pulsar_hecho_dos_veces_no_da_error_y_dice_que_ya_no_esta_activo(
    conn, clock, channel, sent_reminder
):
    press(conn, clock, channel, f"rem_done:{sent_reminder.id}")
    press(conn, clock, channel, f"rem_done:{sent_reminder.id}")
    assert row(conn, sent_reminder.id).status == "done"
    assert "Ya no está activo" in edited(channel)[1]
    assert "llevar tarea" in edited(channel)[1]


def test_hecho_sobre_uno_pendiente_tambien_vale(conn, clock, channel):
    created = reminders.create_reminder(conn, "x", clock() + timedelta(hours=1), clock)
    press(conn, clock, channel, f"rem_done:{created.id}")
    assert row(conn, created.id).status == "done"


# --- +10 min / +1 h ------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [10, 60])
def test_posponer_reprograma_y_dice_para_cuando_conservando_el_texto(
    conn, clock, channel, sent_reminder, minutes
):
    press(conn, clock, channel, f"rem_snooze:{sent_reminder.id}:{minutes}")
    stored = row(conn, sent_reminder.id)
    assert stored.status == "pending" and stored.snooze_count == 1
    assert from_utc_iso(stored.fire_at_utc) == clock() + timedelta(minutes=minutes)
    (text,) = edited(channel)
    assert (
        text.startswith("<b>Pospuesto</b> · ") and " · hoy, " in text
    )  # es hoy: no se repite el día completo
    assert " · llevar tarea · hoy, " in text  # el texto del recordatorio se conserva


def test_posponer_dos_veces_no_da_error_ni_reprograma_otra_vez(conn, clock, channel, sent_reminder):
    press(conn, clock, channel, f"rem_snooze:{sent_reminder.id}:10")
    press(conn, clock, channel, f"rem_snooze:{sent_reminder.id}:60")
    assert row(conn, sent_reminder.id).snooze_count == 1
    assert "Ya no está activo" in edited(channel)[1]


def test_posponer_cruzando_la_medianoche_incluye_el_dia(conn, clock, channel, sent_reminder):
    clock.current = local_to_utc(datetime(2026, 10, 3, 23, 50), TZ)
    press(conn, clock, channel, f"rem_snooze:{sent_reminder.id}:60")
    (text,) = edited(channel)
    assert "domingo 4 de octubre" in text and "hoy" not in text


# --- Mañana --------------------------------------------------------------------------------


def test_manana_dice_el_dia_completo_si_no_es_hoy(conn, clock, channel, sent_reminder):
    press(conn, clock, channel, f"rem_tomorrow:{sent_reminder.id}")
    stored = row(conn, sent_reminder.id)
    assert from_utc_iso(stored.fire_at_utc) == local_to_utc(datetime(2026, 10, 4, 9, 0), TZ)
    assert edited(channel) == ["<b>Pospuesto</b> · llevar tarea · domingo 4 de octubre, 9:00 am"]


def test_manana_de_madrugada_es_hoy_y_el_texto_lo_dice(conn, clock, channel, sent_reminder):
    clock.current = local_to_utc(datetime(2026, 10, 4, 2, 0), TZ)
    press(conn, clock, channel, f"rem_tomorrow:{sent_reminder.id}")
    stored = row(conn, sent_reminder.id)
    assert from_utc_iso(stored.fire_at_utc) == local_to_utc(datetime(2026, 10, 4, 9, 0), TZ)
    assert edited(channel) == ["<b>Pospuesto</b> · llevar tarea · hoy, 9:00 am"]


def test_pulsar_manana_dos_veces_no_da_error(conn, clock, channel, sent_reminder):
    press(conn, clock, channel, f"rem_tomorrow:{sent_reminder.id}")
    press(conn, clock, channel, f"rem_tomorrow:{sent_reminder.id}")
    assert row(conn, sent_reminder.id).snooze_count == 1
    assert "Ya no está activo" in edited(channel)[1]


# --- Ya no está activo / inexistente ------------------------------------------------------------


@pytest.mark.parametrize("template", ["rem_done:{id}", "rem_snooze:{id}:10", "rem_tomorrow:{id}"])
def test_un_recordatorio_cancelado_ya_no_esta_activo(conn, clock, channel, sent_reminder, template):
    reminders.cancel(conn, sent_reminder.id)
    press(conn, clock, channel, template.format(id=sent_reminder.id))
    assert row(conn, sent_reminder.id).status == "cancelled"
    assert len(channel.edits) == 1 and "Ya no está activo" in channel.edits[0][2]


def test_un_id_que_no_existe_ya_no_esta_activo(conn, clock, channel):
    press(conn, clock, channel, "rem_done:999")
    assert edited(channel) == [handlers.NOT_ACTIVE_TEXT]


@pytest.mark.parametrize(
    "choice_id",
    ["rem_done:abc", "rem_done", "rem_done:", "rem_snooze:1", "rem_snooze:1:5", "rem_snooze:1:x"],
)
def test_ids_mal_formados_se_responden_como_opcion_vieja_y_no_tocan_nada(
    conn, clock, channel, sent_reminder, choice_id
):
    press(conn, clock, channel, choice_id)
    assert channel.texts[0][1] == handlers.STALE_CHOICE_TEXT
    assert channel.edits == []
    assert row(conn, sent_reminder.id).status == "sent"


# --- Extraño y consola -------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["rem_done", "rem_tomorrow"])
def test_un_extrano_que_pulsa_un_boton_no_recibe_nada_y_no_cambia_nada(
    conn, clock, channel, sent_reminder, action
):
    press(conn, clock, channel, f"{action}:{sent_reminder.id}", user=99999)
    assert channel.sent_anything is False and channel.edits == []
    assert row(conn, sent_reminder.id).status == "sent"


def test_sin_referencia_al_mensaje_se_responde_con_un_mensaje_nuevo(
    conn, clock, channel, sent_reminder
):
    """La consola no puede editar mensajes anteriores."""
    press(conn, clock, channel, f"rem_done:{sent_reminder.id}", ref=None)
    assert channel.edits == []
    assert channel.texts == [(str(OWNER), "<b>Hecho</b> · llevar tarea", "reply")]
