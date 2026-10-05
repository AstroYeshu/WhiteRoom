"""Corte 3 del rediseño: /pendientes (un solo mensaje), /hoy, /recordatorios, /areas y /ayuda.

Reloj: sábado 2026-10-03 15:30 en México ("mañana" = domingo 4 de octubre). Los textos se comparan
sin etiquetas (`fmt.plain`); que la negrita esté donde debe lo cubre `test_formato.py`.
"""

import logging

import pytest

from asistente import formato as fmt
from asistente.bot import handlers
from asistente.core import areas, reminders, tasks
from tests.botkit import Bot, module_loop  # noqa: F401
from tests.test_commands import add_reminder, add_task, area_id, local, stop

TOAST = "Esa opción ya no aplica"


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def screen(bot: Bot, command: str) -> str:
    """La respuesta a un comando, sin etiquetas."""
    return fmt.plain(bot.reply(command))


def open_titles(conn) -> list[str]:
    return [t.title for t in tasks.list_open(conn)]


def card_text(bot: Bot) -> str:
    return fmt.plain(bot.question[0])


# --- /hoy ----------------------------------------------------------------------------------------


def test_hoy_vacio_tiene_un_estado_cuidado(bot):
    assert screen(bot, "/hoy") == (
        "Hoy · sábado 3 de octubre\n\nNada para hoy: no hay tareas que venzan ni recordatorios."
    )


def test_hoy_vacio_con_bandeja_la_menciona(bot, conn, clock):
    add_task(conn, clock, "suelta")
    add_task(conn, clock, "otra suelta")
    assert screen(bot, "/hoy") == (
        "Hoy · sábado 3 de octubre\n\n"
        "Nada para hoy: no hay tareas que venzan ni recordatorios.\n\n"
        "2 en bandeja sin área"
    )


def test_hoy_con_secciones_horas_cortas_y_bandeja(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_task(conn, clock, "pagar luz", "2026-10-02 17:00")
    add_task(conn, clock, "tarea de mañana", "2026-10-04 09:00")
    add_task(conn, clock, "sin fecha")
    add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00")
    add_reminder(conn, clock, "recordatorio de mañana", "2026-10-04 08:00")
    assert screen(bot, "/hoy") == (
        "Hoy · sábado 3 de octubre\n\n"
        "Tareas\n"
        "Universidad\n"
        "1. Entregar informe · hoy, 5:00 pm\n\n"
        "Sin área\n"
        "2. Pagar luz · vencida vie 2 oct, 5:00 pm\n\n"
        "Recordatorios\n"
        "- hoy, 6:00 pm · Llamar a mamá\n\n"
        "3 en bandeja sin área"
    )


def test_hoy_las_secciones_van_en_negrita(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00")
    html = bot.reply("/hoy")
    assert "<b>Hoy · sábado 3 de octubre</b>" in html and "<b>Tareas</b>" in html


def test_hoy_con_area_filtra_y_no_muestra_la_bandeja(bot, conn, clock):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_task(conn, clock, "regar plantas", "2026-10-03 17:00", "personal")
    add_reminder(conn, clock, "clase", "2026-10-03 19:00", "universidad")
    add_reminder(conn, clock, "gimnasio", "2026-10-03 19:00", "personal")
    add_task(conn, clock, "suelta")
    text = screen(bot, "/hoy Universidad")
    assert text.startswith("Hoy · sábado 3 de octubre · Universidad\n")
    assert "Entregar informe" in text and "Clase" in text
    assert "regar plantas" not in text and "gimnasio" not in text
    assert "bandeja" not in text


def test_hoy_con_un_area_que_no_existe(bot):
    assert screen(bot, "/hoy inventada") == (
        "Aviso · No encuentro el área «inventada». Escribe /areas para ver las que hay."
    )


def test_hoy_los_recordatorios_detenidos_se_marcan(bot, conn, clock):
    stopped = add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00")
    stop(conn, stopped.id, "permanent:bot_blocked")
    assert "- hoy, 6:00 pm · Llamar a mamá · detenido" in screen(bot, "/hoy")


def test_hoy_limita_cada_seccion(bot, conn, clock):
    for number in range(17):
        add_reminder(conn, clock, f"r{number}", "2026-10-03 18:00")
    text = screen(bot, "/hoy")
    assert text.count("\n- ") == 15
    assert "y 2 más" in text


def test_hoy_cerca_de_medianoche_el_dia_termina_a_las_00_00_locales(bot, conn, clock):
    clock.current = local("2026-10-03 23:50")
    add_task(conn, clock, "justo antes", "2026-10-03 23:59")
    add_task(conn, clock, "justo a medianoche", "2026-10-04 00:00")
    add_task(conn, clock, "ya es mañana", "2026-10-04 00:30")
    add_reminder(conn, clock, "aviso de hoy", "2026-10-03 23:55")
    add_reminder(conn, clock, "aviso de mañana", "2026-10-04 00:05")
    text = screen(bot, "/hoy")
    assert "Sin área\n1. Justo antes · hoy, 11:59 pm" in text
    assert "- hoy, 11:55 pm · Aviso de hoy" in text
    assert "justo a medianoche" not in text and "ya es mañana" not in text
    assert "aviso de mañana" not in text


def test_hoy_pasada_la_medianoche_ya_es_otro_dia(bot, conn, clock):
    clock.current = local("2026-10-04 00:10")
    add_task(conn, clock, "de anoche", "2026-10-03 23:59")
    add_task(conn, clock, "recién empezado", "2026-10-04 00:05")
    add_task(conn, clock, "fin del día", "2026-10-04 23:59")
    add_task(conn, clock, "mañana a las 00", "2026-10-05 00:00")
    text = screen(bot, "/hoy")
    assert text.startswith("Hoy · domingo 4 de octubre\n")
    assert "1. De anoche · vencida sáb 3 oct, 11:59 pm" in text
    assert "2. Recién empezado · hoy, 12:05 am" in text
    assert "3. Fin del día · hoy, 11:59 pm" in text
    assert "mañana a las 00" not in text


# --- /pendientes: un solo mensaje ----------------------------------------------------------------


def test_pendientes_sin_tareas(bot):
    assert (
        screen(bot, "/pendientes") == "Pendientes (0)\n\nNo tienes tareas pendientes. Todo al día."
    )


def test_pendientes_es_un_solo_mensaje_con_lista_numerada_y_un_boton_por_numero(bot, conn, clock):
    add_task(conn, clock, "sin fecha")
    add_task(conn, clock, "con fecha", "2026-10-04 09:00", "universidad")
    done = add_task(conn, clock, "ya hecha")
    tasks.mark_done(conn, done.id, clock)
    bot.say("/pendientes")
    assert bot.sent_count() == 1
    assert fmt.plain(bot.messages()[0]) == (
        "Pendientes (2)\n\nUniversidad\n1. Con fecha · mañana, 9:00 am\n\nSin área\n2. Sin fecha"
    )
    assert "<b>Pendientes (2)</b>" in bot.messages()[0]
    assert bot.labels() == ["1", "2"]


def test_pendientes_con_area_la_pone_en_el_titulo(bot, conn, clock):
    add_task(conn, clock, "de la uni", area="universidad")
    add_task(conn, clock, "personal", area="personal")
    assert screen(bot, "/pendientes universidad") == "Pendientes · Universidad (1)\n\n1. De la uni"


def test_pendientes_con_un_area_que_no_existe(bot):
    assert screen(bot, "/pendientes nada").startswith("Aviso · No encuentro el área")


def test_pendientes_limita_a_15_y_avisa_cuantas_faltan(bot, conn, clock):
    for number in range(18):
        add_task(conn, clock, f"tarea {number:02d}")
    bot.say("/pendientes")
    text = fmt.plain(bot.messages()[0])
    assert text.startswith("Pendientes (18)\n\nSin área\n1. Tarea 00\n")
    assert "15. Tarea 14" in text and "16." not in text
    assert text.endswith("y 3 más: filtra por área (/pendientes nombre)")
    assert bot.labels() == [str(n) for n in range(1, 16)]
    assert bot.channel.layouts[-1] == (5, 5, 5)  # los números van de a 5 por fila


def test_un_numero_muestra_la_tarea_en_el_mismo_mensaje_con_hecha_descartar_y_volver(
    bot, conn, clock
):
    add_task(conn, clock, "con fecha", "2026-10-04 09:00", "universidad")
    add_task(conn, clock, "sin fecha")
    bot.say("/pendientes")
    bot.tap("1")
    assert bot.sent_count() == 1
    assert card_text(bot) == (
        "Con fecha\n\nÁrea: Universidad\nVence: mañana, 9:00 am\n\n¿Qué hago con esta tarea?"
    )
    assert bot.labels() == ["Hecha", "Descartar", "Volver"]
    assert bot.channel.edit_keyboards[-1][1] == (2, 1)


def test_hecha_cierra_esa_tarea_y_vuelve_a_la_lista_actualizada(bot, conn, clock):
    add_task(conn, clock, "primera")
    second = add_task(conn, clock, "segunda")
    add_task(conn, clock, "tercera")
    bot.say("/pendientes")
    bot.tap("2")
    bot.tap("Hecha")
    assert tasks.get_task(conn, second.id).status == "done"
    assert open_titles(conn) == ["primera", "tercera"]  # solo cayó esa
    assert card_text(bot) == (
        "Pendientes (2)\n\nSin área\n1. Primera\n2. Tercera\n\nHecha · Segunda"
    )
    assert bot.labels() == ["1", "2"]
    assert bot.sent_count() == 1


def test_hecha_sobre_la_tarea_elegida_aunque_haya_otras_antes(bot, conn, clock):
    for title in ("a", "b", "c", "d"):
        add_task(conn, clock, title)
    bot.say("/pendientes")
    bot.tap("3")
    bot.tap("Hecha")
    assert open_titles(conn) == ["a", "b", "d"]


def test_descartar_es_soft_delete_con_motivo_y_vuelve_a_la_lista(bot, conn, clock):
    task = add_task(conn, clock, "comprar pan")
    add_task(conn, clock, "otra")
    bot.say("/pendientes")
    bot.tap("1")
    bot.tap("Descartar")
    stored = tasks.get_task(conn, task.id)
    assert (stored.status, stored.closed_reason) == ("dropped", "discarded")
    assert card_text(bot) == "Pendientes (1)\n\nSin área\n1. Otra\n\nDescartada · Comprar pan"


def test_volver_regresa_a_la_lista_sin_cambiar_nada(bot, conn, clock):
    add_task(conn, clock, "una")
    add_task(conn, clock, "dos")
    bot.say("/pendientes")
    first = card_text(bot)
    bot.tap("2")
    bot.tap("Volver")
    assert card_text(bot) == first
    assert open_titles(conn) == ["una", "dos"]


def test_al_cerrar_la_ultima_tarea_queda_el_estado_vacio_sin_botones(bot, conn, clock):
    add_task(conn, clock, "única")
    bot.say("/pendientes")
    bot.tap("1")
    bot.tap("Hecha")
    assert fmt.plain(bot.last[1]) == (
        "Pendientes (0)\n\nNo tienes tareas pendientes. Todo al día.\n\nHecha · Única"
    )
    assert bot.last[2] == []


def test_con_area_la_lista_actualizada_conserva_el_filtro(bot, conn, clock):
    add_task(conn, clock, "uni 1", area="universidad")
    add_task(conn, clock, "uni 2", area="universidad")
    add_task(conn, clock, "personal", area="personal")
    bot.say("/pendientes universidad")
    bot.tap("1")
    bot.tap("Hecha")
    assert card_text(bot) == "Pendientes · Universidad (1)\n\n1. Uni 2\n\nHecha · Uni 1"


def test_un_numero_de_una_tarea_ya_cerrada_responde_con_el_aviso_y_actualiza_la_lista(
    bot, conn, clock
):
    gone = add_task(conn, clock, "cerrada afuera")
    add_task(conn, clock, "sigue")
    bot.say("/pendientes")
    open_gone = bot.choice_id("1")
    tasks.mark_done(conn, gone.id, clock)
    assert bot.press(open_gone) == TOAST
    assert card_text(bot) == "Pendientes (1)\n\nSin área\n1. Sigue"  # la lista ya no la muestra
    assert bot.sent_count() == 1


def test_hecha_dos_veces_la_segunda_responde_con_el_aviso(bot, conn, clock):
    add_task(conn, clock, "una")
    add_task(conn, clock, "dos")
    bot.say("/pendientes")
    bot.tap("1")
    done = bot.choice_id("Hecha")
    assert bot.press(done) is None
    assert bot.press(done) == TOAST
    assert open_titles(conn) == ["dos"]


def test_hecha_sobre_una_tarea_descartada_afuera_no_la_pisa(bot, conn, clock):
    task = add_task(conn, clock, "cambia afuera")
    add_task(conn, clock, "otra")
    bot.say("/pendientes")
    bot.tap("1")
    done = bot.choice_id("Hecha")
    tasks.drop_task(conn, task.id, clock)
    assert bot.press(done) == TOAST
    assert tasks.get_task(conn, task.id).status == "dropped"  # no se cambió a done


def test_los_botones_de_pendientes_sobreviven_a_un_reinicio(bot, conn, clock):
    add_task(conn, clock, "una")
    bot.say("/pendientes")
    bot.restart()
    bot.tap("1")
    bot.tap("Hecha")
    assert open_titles(conn) == []


def test_hecha_cancela_los_avisos_de_preparacion(bot, conn, clock):
    task = tasks.create_task(conn, "entrega", clock, due_at_utc=local("2026-10-05 09:00"))
    assert reminders.list_pending(conn)
    bot.say("/pendientes")
    bot.tap("1")
    bot.tap("Hecha")
    assert tasks.get_task(conn, task.id).status == "done"
    assert reminders.list_pending(conn) == []


@pytest.mark.parametrize(
    "choice_id",
    ["pd", "pd:x", "pd:o", "pd:o:1", "pd:o:a:b", "pd:z:0:1", "pd:o:0:99999", "pd:h:0", "pd:b:x"],
)
def test_botones_de_pendientes_mal_formados_o_inexistentes_no_hacen_dano(
    bot, conn, clock, choice_id
):
    add_task(conn, clock, "una")
    bot.say("/pendientes")
    before = len(bot.channel.log)
    toast = bot.press(choice_id)
    assert toast in (TOAST, None)
    assert open_titles(conn) == ["una"]
    assert len(bot.channel.log) - before <= 1


def test_pendientes_escapa_el_texto_del_usuario(bot, conn, clock):
    hostile = '<b>x</b> & "q" *a*'
    add_task(conn, clock, hostile)
    bot.say("/pendientes")
    html = bot.messages()[0]
    assert "<b>x</b> &" not in html  # la negrita del usuario no se interpreta
    assert fmt.plain(html).endswith(f"1. {hostile}")
    bot.tap("1")
    assert fmt.plain(bot.question[0]).startswith(hostile)


# --- /recordatorios: pendientes y detenidos por separado -----------------------------------------


def test_recordatorios_sin_pendientes(bot):
    assert screen(bot, "/recordatorios") == "Recordatorios\n\nNo tienes recordatorios pendientes."


def test_recordatorios_lista_pendientes_con_area_y_repeticion(bot, conn, clock):
    add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00", "universidad")
    add_reminder(conn, clock, "regar plantas", "2026-10-05 19:00", rrule="FREQ=WEEKLY;BYDAY=MO")
    done = add_reminder(conn, clock, "ya hecho", "2026-10-04 07:00")
    reminders.mark_done(conn, done.id)
    assert screen(bot, "/recordatorios") == (
        "Recordatorios\n\nPendientes (2)\n"
        "- mañana, 8:00 am · Llevar tarea · Universidad\n"
        "- lun 5 oct, 7:00 pm · Regar plantas · Cada lunes"
    )


def test_recordatorios_separa_los_detenidos_en_su_propia_seccion(bot, conn, clock):
    add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00")
    blocked = add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00")
    stop(conn, blocked.id, "permanent:bot_blocked")
    text = screen(bot, "/recordatorios")
    assert text == (
        "Recordatorios\n\nPendientes (1)\n- mañana, 8:00 am · Llevar tarea\n\n"
        "Detenidos (1)\n- hoy, 6:00 pm · Llamar a mamá · Motivo: el bot está bloqueado en tu chat"
    )
    pending_section, stopped_section = text.split("\n\n")[1:]
    assert "llamar a mamá" not in pending_section  # un detenido nunca va entre los pendientes
    assert "llevar tarea" not in stopped_section


def test_recordatorios_solo_detenidos_no_muestra_la_seccion_de_pendientes(bot, conn, clock):
    blocked = add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00")
    stop(conn, blocked.id, "horizon:telegram_down")
    text = screen(bot, "/recordatorios")
    assert "Pendientes" not in text
    assert "Motivo: Telegram no respondió durante 24 horas" in text


def test_recordatorios_las_secciones_van_en_negrita(bot, conn, clock):
    add_reminder(conn, clock, "x", "2026-10-04 08:00")
    stop(conn, add_reminder(conn, clock, "y", "2026-10-04 09:00").id, "legacy")
    html = bot.reply("/recordatorios")
    assert "<b>Pendientes (1)</b>" in html and "<b>Detenidos (1)</b>" in html


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("permanent:bot_blocked", "el bot está bloqueado en tu chat"),
        ("permanent:chat_not_found", "no se encontró tu chat"),
        ("permanent:message_too_long", "el mensaje era demasiado largo"),
        ("permanent:bad_request:cant_parse_entities", "Telegram no pudo leer el formato del texto"),
        ("permanent:bad_request:empty_text", "el texto estaba vacío"),
        ("permanent:bad_request:button_data_invalid", "un botón no era válido"),
        ("permanent:bad_request:other", "Telegram rechazó el mensaje"),
        ("horizon:telegram_down", "Telegram no respondió durante 24 horas"),
        ("legacy", "se detuvo en una versión anterior"),
        ("permanent:telegram_error:Conflict", "error inesperado al enviar"),
        ("permanent:unexpected:KeyError", "error inesperado al enviar"),
    ],
)
def test_los_detenidos_se_explican_en_lenguaje_claro(bot, conn, clock, code, expected):
    stopped = add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00")
    stop(conn, stopped.id, code)
    text = screen(bot, "/recordatorios")
    assert f"- mañana, 8:00 am · Llevar tarea · Motivo: {expected}" in text
    assert code not in text  # el código crudo nunca llega al usuario


@pytest.mark.parametrize("code", ["permanent:algo_raro", "horizon:otro", "", "xyz"])
def test_un_codigo_desconocido_dice_motivo_desconocido_y_el_codigo_solo_va_al_log(
    bot, conn, clock, caplog, code
):
    stopped = add_reminder(conn, clock, "llevar tarea", "2026-10-04 08:00")
    stop(conn, stopped.id, code)
    with caplog.at_level(logging.WARNING):
        text = screen(bot, "/recordatorios")
    assert "· Motivo: motivo desconocido" in text
    if code:
        assert code not in text
        assert code in caplog.text
    assert "llevar tarea" not in caplog.text  # el texto del usuario nunca va al log


def test_recordatorios_limita_cada_seccion(bot, conn, clock):
    for number in range(22):
        add_reminder(conn, clock, f"r{number}", "2026-10-04 08:00")
    text = screen(bot, "/recordatorios")
    assert text.count("\n- ") == 20
    assert "y 2 más" in text


# --- /areas y /ayuda -----------------------------------------------------------------------------


def test_areas_lista_y_marca_las_que_no_tienen_descripcion(bot, conn, clock):
    areas.create_area(conn, "Salud", "", clock)
    assert screen(bot, "/areas") == (
        "Áreas (5)\n\n- Universidad\n- Proyectos\n- Iglesia\n- Personal\n- Salud · sin descripción"
    )


def test_areas_no_lista_las_archivadas(bot, conn):
    areas.archive_area(conn, area_id(conn, "iglesia"))
    text = screen(bot, "/areas")
    assert "iglesia" not in text and text.startswith("Áreas (3)")


def test_areas_sin_areas(bot, conn):
    for area in areas.list_areas(conn):
        areas.archive_area(conn, area.id)
    assert screen(bot, "/areas") == "Áreas\n\nNo hay áreas. Crea una con /nuevaarea nombre."


def test_ayuda_esta_agrupada_por_tipo_de_comando(bot):
    text = screen(bot, "/ayuda")
    assert text == (
        "Ayuda\n\n"
        "Anotar\n"
        "Escribe cualquier mensaje: lo guardo en tu bandeja y te pregunto qué es.\n"
        "/tarea texto · guardar una tarea\n"
        "/nota texto · guardar una nota\n"
        "/recordar texto · crear un recordatorio con su fecha\n\n"
        "Consultar\n"
        "/hoy [área] · lo que vence hoy\n"
        "/pendientes [área] · tus tareas abiertas\n"
        "/recordatorios · avisos pendientes y detenidos\n\n"
        "Áreas\n"
        "/areas · ver las áreas\n"
        "/nuevaarea nombre · crear un área\n\n"
        "Otros\n"
        "/estado · estado del bot\n"
        "/start · saludo\n"
        "/ayuda · esta lista"
    )
    assert "/papelera" not in text
    assert handlers.HELP_TEXT == fmt.HELP
    assert "<b>Anotar</b>" in bot.channel.log[-1][1]


def test_start_saluda(bot):
    text = screen(bot, "/start")
    assert text.startswith("Hola, soy tu asistente personal\n\n")
    assert "/ayuda" in text


def test_los_errores_de_uso_tienen_el_formato_de_aviso(bot):
    assert screen(bot, "/recordar") == (
        "Aviso · Escribe /recordar seguido de qué y cuándo, "
        "por ejemplo: /recordar mañana 8 am llevar tarea"
    )
    assert screen(bot, "/tarea").startswith("Aviso · Escribe /tarea")
    assert screen(bot, "/nota").startswith("Aviso · Escribe /nota")
    assert screen(bot, "/nuevaarea").startswith("Aviso · Escribe /nuevaarea")
    assert screen(bot, "/inventado") == (
        "Aviso · No conozco ese comando. Escribe /ayuda para ver los disponibles."
    )


@pytest.mark.parametrize("text", ["/hoy", "/pendientes", "/recordatorios", "/areas", "/ayuda"])
def test_un_extrano_no_recibe_nada(bot, text):
    bot.say(text, user=99999)
    assert bot.channel.sent_anything is False


def test_un_extrano_no_puede_pulsar_un_boton_de_pendientes(bot, conn, clock):
    add_task(conn, clock, "una")
    bot.say("/pendientes")
    button = bot.choice_id("1")
    before = len(bot.channel.log)
    assert bot.press(button, user=99999) is None
    assert len(bot.channel.log) == before


# --- huecos detectados al comparar con las pruebas quitadas en el corte 3 -------------------------


def test_hoy_con_avisos_pero_sin_bandeja_no_menciona_la_bandeja(bot, conn, clock):
    add_reminder(conn, clock, "llamar", "2026-10-03 18:00")
    assert "bandeja" not in screen(bot, "/hoy")


def test_las_vistas_escapan_el_texto_del_usuario(bot, conn, clock):
    hostile = "<i>x</i> & <b>"
    add_task(conn, clock, hostile, "2026-10-03 17:00")
    add_reminder(conn, clock, hostile, "2026-10-03 18:00")
    for command in ("/hoy", "/recordatorios"):
        bot.say(command)
        html = bot.messages()[-1]
        assert "<i>x</i>" not in html, command
        assert "&lt;i&gt;x&lt;/i&gt; &amp; &lt;b&gt;" in html, command


def test_los_botones_de_pendientes_no_registran_el_texto_del_usuario(bot, conn, clock, caplog):
    secret = "secretoultraprivado"
    add_task(conn, clock, secret + " uno")
    add_task(conn, clock, secret + " dos")
    with caplog.at_level(logging.DEBUG):
        bot.say("/pendientes")
        bot.tap("1")
        bot.tap("Hecha")
        bot.tap("1")
        bot.tap("Descartar")
        bot.say("/areas")
        bot.say("/hoy")
        bot.say("/recordatorios")
    assert secret not in caplog.text


def test_hoy_un_aviso_a_las_00_00_exactas_ya_es_de_manana(bot, conn, clock):
    clock.current = local("2026-10-03 23:50")
    add_reminder(conn, clock, "justo a medianoche", "2026-10-04 00:00")
    add_reminder(conn, clock, "un minuto antes", "2026-10-03 23:59")
    text = screen(bot, "/hoy")
    assert "Un minuto antes" in text
    assert "justo a medianoche" not in text
