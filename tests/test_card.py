"""Corte 2 del rediseño: la captura es UN solo mensaje que evoluciona (una "tarjeta").

El mensaje libre abre la tarjeta; cada paso (tipo, área, fecha, confirmación) la EDITA en su lugar
con el texto y los botones nuevos. Un botón viejo sobre la tarjeta viva se ignora en silencio; sobre
una tarjeta muerta la marca como no disponible. Reloj: sábado 2026-10-03 15:30 en México.
"""

import pytest

from asistente import formato as fmt
from asistente.core import areas, reminders, tasks
from tests.botkit import Bot, module_loop  # noqa: F401


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def plain(bot: Bot, ref: str | None = None) -> str:
    """El texto actual de la tarjeta (sin etiquetas)."""
    return fmt.plain(bot.text_of(ref or bot.question_ref))


def card_ref(bot: Bot) -> str:
    return bot.channel.refs[0]


def all_tasks(conn) -> list[tasks.Task]:
    return [tasks.get_task(conn, row["id"]) for row in conn.execute("SELECT id FROM tasks")]


def layouts_of_edits(bot: Bot):
    return [layout for _, layout in bot.channel.edit_keyboards]


# --- Un solo mensaje por captura -------------------------------------------------------------


def test_una_tarea_es_un_solo_mensaje_que_evoluciona(bot, conn):
    bot.say("comprar leche")
    assert bot.sent_count() == 1
    assert plain(bot) == "¿Qué es?\n\ncomprar leche"
    bot.tap("Tarea")
    assert plain(bot) == "¿En qué área va?\n\ncomprar leche\n\nTipo: Tarea"
    bot.tap("personal")
    assert bot.sent_count() == 1
    assert plain(bot, card_ref(bot)) == "Tarea guardada\n\ncomprar leche\n\nÁrea: personal"
    assert bot.channel.log[-1][2] == []  # la tarjeta final no lleva botones
    assert {ref for ref in bot.channel.refs} == {card_ref(bot)}  # todo pasó en el MISMO mensaje


def test_una_nota_es_un_solo_mensaje(bot, conn):
    bot.say("la clave del wifi es larga")
    bot.tap("Nota")
    bot.tap("universidad")
    assert bot.sent_count() == 1
    assert plain(bot, card_ref(bot)) == (
        "Nota guardada\n\nla clave del wifi es larga\n\nÁrea: universidad"
    )


def test_un_recordatorio_es_un_solo_mensaje_hasta_deshacer(bot, conn):
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("universidad")
    assert bot.sent_count() == 1
    assert plain(bot) == (
        "Recordatorio guardado\n\nllevar tarea\n\n"
        "Cuándo: domingo 4 de octubre, 8:00 am\nÁrea: universidad"
    )
    assert bot.labels() == ["Cambiar", "Deshacer"]
    assert layouts_of_edits(bot)[-1] == (2,)
    bot.tap("Deshacer")
    assert bot.sent_count() == 1
    assert plain(bot, card_ref(bot)) == "Deshecho · llevar tarea · vuelve a tu bandeja como tarea"


def test_cambiar_sigue_en_el_mismo_mensaje(bot, conn):
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("iglesia")
    bot.tap("Cambiar")
    assert bot.sent_count() == 1
    assert plain(bot).startswith("¿Cuándo?\n\nllevar tarea\n\nTipo: Recordatorio\nÁrea: iglesia")
    bot.say("pasado mañana 10 am")
    assert bot.sent_count() == 1
    assert "Recordatorio guardado" in plain(bot, card_ref(bot))
    assert "lunes 5 de octubre, 10:00 am" in plain(bot, card_ref(bot))


def test_la_pregunta_del_parser_vive_en_la_misma_tarjeta_con_botones_de_dos_en_dos(bot, conn):
    bot.say("mañana a las 9 llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert bot.sent_count() == 1
    assert plain(bot).startswith("¿A las 9 am o pm?\n\nllevar tarea")
    assert bot.labels() == ["mañana, 9:00 am", "mañana, 9:00 pm", "Otra fecha", "Cancelar"]
    assert layouts_of_edits(bot)[-1] == (
        2,
        2,
    )  # candidatos de 2 por fila; Otra fecha y Cancelar abajo
    bot.tap("mañana, 9:00 pm")
    assert bot.sent_count() == 1
    assert "Recordatorio guardado" in plain(bot, card_ref(bot))


def test_cada_comando_de_captura_es_un_solo_mensaje(bot, conn):
    bot.say("/tarea comprar pan")
    bot.tap("personal")
    bot.say("/nota la clave")
    bot.tap("Sin área")
    bot.say("/recordar mañana 8am llevar tarea")
    bot.tap("Sin área")
    bot.tap("Guardar")
    assert bot.sent_count() == 3  # uno por captura
    assert [plain(bot, ref) for ref in dict.fromkeys(bot.channel.refs)][-1].startswith(
        "Recordatorio guardado"
    )


def test_la_vista_previa_de_recordar_y_la_confirmacion_son_la_misma_tarjeta(bot, conn):
    bot.say("/recordar mañana 8am llevar tarea")
    bot.tap("universidad")
    assert plain(bot) == (
        "¿Guardo este recordatorio?\n\nllevar tarea\n\n"
        "Cuándo: domingo 4 de octubre, 8:00 am\nÁrea: universidad"
    )
    assert bot.labels() == ["Guardar", "Cancelar"]
    assert reminders.list_pending(conn) == []
    bot.tap("Guardar")
    assert bot.sent_count() == 1
    assert plain(bot).startswith("Recordatorio guardado")


def test_la_repeticion_muestra_la_interpretacion_en_la_tarjeta(bot, conn):
    bot.say("todos los lunes a las 7 pm regar plantas")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    assert plain(bot) == (
        "¿Guardo esta repetición?\n\nregar plantas\n\n"
        "Repetición: Cada lunes\nPróxima: lunes 5 de octubre, 7:00 pm"
    )
    bot.tap("Guardar")
    assert bot.sent_count() == 1
    assert "Repetición: Cada lunes" in plain(bot)


def test_dos_capturas_son_dos_mensajes(bot, conn):
    bot.say("comprar leche")
    bot.tap("Tarea")
    bot.tap("Sin área")
    bot.say("sacar copias")
    bot.tap("Nota")
    bot.tap("Sin área")
    assert bot.sent_count() == 2
    assert len(set(bot.channel.refs)) == 2


def test_cancelar_deja_la_tarjeta_como_cancelada(bot, conn):
    bot.say("comprar leche")
    bot.tap("Cancelar")
    assert (
        plain(bot, card_ref(bot)) == "Cancelado\n\ncomprar leche\n\nSigue en tu bandeja como tarea."
    )
    assert bot.channel.log[-1][2] == []
    assert bot.sent_count() == 1


def test_mejor_como_tarea_cierra_la_tarjeta_como_tarea_guardada(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("iglesia")
    assert bot.labels() == ["Hoy 6:00 pm", "Mañana 9:00 am", "Mejor como tarea", "Cancelar"]
    assert layouts_of_edits(bot)[-1] == (2, 2)
    bot.tap("Mejor como tarea")
    assert plain(bot, card_ref(bot)) == "Tarea guardada\n\nllamar al dentista\n\nÁrea: iglesia"
    assert bot.sent_count() == 1


def test_la_fecha_limite_tambien_vive_en_la_tarjeta(bot, conn):
    bot.say("/tarea entregar informe el viernes")
    bot.tap("universidad")
    assert plain(bot) == (
        "¿Es la fecha límite?\n\nentregar informe\n\n"
        "Tipo: Tarea\nÁrea: universidad\nFecha: viernes 9 de octubre, 9:00 am (hora por defecto)"
    )
    assert bot.labels() == ["Sí", "No", "Cancelar"]
    assert layouts_of_edits(bot)[-1] == (2, 1)
    bot.tap("Sí")
    assert bot.sent_count() == 1
    assert plain(bot, card_ref(bot)).startswith("Tarea guardada\n\nentregar informe")


def test_nuevaarea_tambien_es_una_tarjeta(bot, conn):
    bot.say("/nuevaarea Salud")
    assert plain(bot) == "¿Qué cubre «Salud»?\n\nEscribe una descripción corta u omítela."
    assert bot.labels() == ["Omitir", "Cancelar"]
    bot.say("Ejercicio y citas médicas")
    assert bot.sent_count() == 1
    assert plain(bot, card_ref(bot)) == "Área guardada\n\nSalud\n\nEjercicio y citas médicas"
    assert areas.find_area_by_name(conn, "Salud").description == "Ejercicio y citas médicas"


# --- Mensaje nuevo a mitad de una tarjeta --------------------------------------------------------


def test_un_mensaje_nuevo_marca_la_tarjeta_anterior_como_sin_terminar_sin_otro_mensaje(bot, conn):
    bot.say("comprar leche")
    first = card_ref(bot)
    bot.say("sacar copias")
    assert bot.sent_count() == 2  # la tarjeta vieja se EDITA; solo se abre la nueva
    assert plain(bot, first) == "Sin terminar\n\ncomprar leche\n\nSigue en tu bandeja como tarea."
    assert plain(bot).startswith("¿Qué es?\n\nsacar copias")
    assert [t.status for t in all_tasks(conn)] == ["open", "open"]


def test_responder_la_fecha_con_texto_edita_la_tarjeta(bot, conn):
    bot.say("llamar al dentista")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    bot.say("mañana 10 am")
    assert bot.sent_count() == 1
    assert "Recordatorio guardado" in plain(bot, card_ref(bot))


# --- Botones viejos ------------------------------------------------------------------------------


def test_un_boton_viejo_sobre_la_tarjeta_viva_se_ignora_en_silencio(bot, conn):
    bot.say("comprar leche")
    old_kind = bot.choice_id("Tarea")
    bot.tap("Recordatorio")  # la tarjeta pasa a la pregunta de área
    before = len(bot.channel.log)
    bot.press(old_kind)  # el botón de tipo ya no es el vigente
    assert len(bot.channel.log) == before  # ni edición ni mensaje nuevo
    assert "¿En qué área va?" in plain(bot)
    bot.tap("personal")  # y la tarjeta viva sigue funcionando
    assert "¿Cuándo?" in plain(bot)


def test_pulsar_dos_veces_el_mismo_boton_no_hace_nada_la_segunda(bot, conn):
    bot.say("comprar leche")
    button = bot.choice_id("Nota")
    bot.press(button)
    before = len(bot.channel.log)
    bot.press(button)
    assert len(bot.channel.log) == before
    assert bot.sent_count() == 1
    assert "¿En qué área va?" in plain(bot)


def test_un_boton_de_una_tarjeta_muerta_la_marca_como_no_disponible(bot, conn):
    bot.say("comprar leche")
    dead_button = bot.choice_id("Tarea")
    first = card_ref(bot)
    bot.say("sacar copias")  # la primera tarjeta queda sin terminar
    bot.press(dead_button)
    assert plain(bot, first) == "Aviso · Esa opción ya no está disponible."
    assert bot.sent_count() == 2
    assert plain(bot).startswith("¿Qué es?\n\nsacar copias")  # la tarjeta viva no se tocó
    bot.tap("Tarea")
    assert "¿En qué área va?" in plain(bot)


def test_tras_reiniciar_un_boton_viejo_marca_la_tarjeta_y_no_se_pierde_nada(bot, conn):
    bot.say("comprar leche")
    button = bot.choice_id("Tarea")
    bot.restart()
    bot.press(button)
    assert plain(bot, card_ref(bot)) == "Aviso · Esa opción ya no está disponible."
    assert bot.sent_count() == 1
    assert [(t.title, t.status) for t in all_tasks(conn)] == [("comprar leche", "open")]


def test_deshacer_dos_veces_no_pisa_la_tarjeta(bot, conn):
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("Sin área")
    undo = bot.choice_id("Deshacer")
    change = bot.choice_id("Cambiar")
    bot.press(change)  # la tarjeta pasa a ¿Cuándo? (sigue viva)
    before = len(bot.channel.log)
    bot.press(undo)  # el botón viejo del mensaje de confirmación
    bot.press(change)
    assert len(bot.channel.log) == before
    assert "¿Cuándo?" in plain(bot)


# --- Un canal que no puede editar ----------------------------------------------------------------


def test_sin_edicion_el_flujo_se_completa_con_mensajes_nuevos(conn, clock):
    bot = Bot(conn, clock, editable=False)
    bot.say("mañana 8am llevar tarea")
    bot.tap("Recordatorio")
    bot.tap("universidad")
    assert bot.sent_count() == 3  # tarjeta, pregunta de área y confirmación
    [reminder] = reminders.list_pending(conn)
    assert reminder.text == "llevar tarea"
    assert "Recordatorio guardado" in fmt.plain(bot.last[1])
    bot.tap("Deshacer")
    assert reminders.list_pending(conn) == []
    assert all_tasks(conn)[0].status == "open"


def test_si_la_edicion_falla_a_mitad_se_sigue_en_un_mensaje_nuevo(conn, clock):
    bot = Bot(conn, clock)
    bot.say("comprar leche")
    bot.tap("Tarea")
    bot.channel.editable = False  # p. ej. Telegram no deja editar un mensaje muy viejo
    bot.tap("personal")
    assert "Tarea guardada" in fmt.plain(bot.last[1])
    assert bot.sent_count() == 2
