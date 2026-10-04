"""Corte 1 del rediseño: `formato.py` (funciones puras de presentación).

Reloj: sábado 2026-10-03 15:30 en México. Principios: marcado mínimo (<b>, <i>, <code>), el
texto del usuario SIEMPRE escapado, fechas corta (botones y listas) y larga (confirmaciones),
cuadrícula de botones como dato, etiquetas de botón de 22 caracteres como máximo.
"""

from datetime import datetime, timedelta

import pytest

from asistente import formato as fmt
from asistente.formato import Html
from asistente.timeutil import local_to_utc
from tests.botkit import TZ
from tests.htmlcheck import html_problems
from tests.test_no_pictograms import find_pictograms

HOSTILE = [
    "<b>negrita</b>",
    "a < b > c & d",
    "*x* _y_ [z](http://e.com) `c`",
    "\"comillas\" 'simples'",
    "&lt;ya escapado&gt; &amp;",
    "</b></i></code> <code>",
    "<script>alert(1)</script>",
]


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


@pytest.fixture
def now(clock):
    return clock  # sábado 3 de octubre de 2026, 15:30 en México


# --- esc y los constructores escapan siempre -----------------------------------------------------


def test_esc_escapa_solo_lo_que_telegram_exige():
    assert fmt.esc("<b>a</b> & \"c\" 'd'") == "&lt;b&gt;a&lt;/b&gt; &amp; \"c\" 'd'"


@pytest.mark.parametrize("text", HOSTILE)
def test_los_constructores_escapan_el_texto_del_usuario(text):
    for built in (fmt.bold(text), fmt.italic(text), fmt.code(text), fmt.block(text, text)):
        assert isinstance(built, Html)
        assert html_problems(built) == []
    assert fmt.bold(text) == Html(f"<b>{fmt.esc(text)}</b>")


def test_un_html_ya_seguro_no_se_escapa_dos_veces():
    inner = fmt.italic("a<b")
    assert fmt.bold(inner) == Html("<b><i>a&lt;b</i></b>")


def test_un_texto_plano_se_trata_como_texto_no_como_html():
    assert fmt.to_html("a <b>b</b>") == "a &lt;b&gt;b&lt;/b&gt;"
    assert fmt.to_html(fmt.bold("x")) == "<b>x</b>"


def test_plain_quita_las_etiquetas_y_deshace_las_entidades():
    assert fmt.plain(fmt.block(fmt.bold("a<b"), "x & y")) == "a<b\nx & y"
    assert fmt.plain("texto <plano>") == "texto <plano>"  # un str no se toca


@pytest.mark.parametrize("text", HOSTILE)
def test_plain_devuelve_exactamente_lo_que_escribio_el_usuario(text):
    assert fmt.plain(fmt.bold(text)) == text


def test_block_y_paragraphs_separan_con_lineas():
    assert fmt.block("a", fmt.bold("b")) == Html("a\n<b>b</b>")
    assert fmt.paragraphs("a", "b") == Html("a\n\nb")


# --- Fechas --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("2026-10-03 18:00", "hoy, 6:00 pm"),
        ("2026-10-03 10:00", "hoy, 10:00 am"),
        ("2026-10-04 08:00", "mañana, 8:00 am"),
        ("2026-10-05 09:00", "lun 5 oct, 9:00 am"),
        ("2026-10-09 09:00", "vie 9 oct, 9:00 am"),
        ("2026-12-25 20:30", "vie 25 dic, 8:30 pm"),
        ("2027-03-14 08:00", "14 mar 2027, 8:00 am"),  # otro año: sin día de la semana
        ("2026-10-04 00:00", "mañana, 12:00 am"),
        ("2026-10-03 12:00", "hoy, 12:00 pm"),
    ],
)
def test_fecha_corta(now, when, expected):
    assert fmt.fecha_corta(local(when), TZ, now) == expected


def test_fecha_corta_usa_el_dia_local_no_el_de_utc(now):
    assert fmt.fecha_corta(local("2026-10-03 23:59"), TZ, now) == "hoy, 11:59 pm"
    assert fmt.fecha_corta(local("2026-10-04 00:00"), TZ, now) == "mañana, 12:00 am"


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("2026-10-03 18:00", "sábado 3 de octubre, 6:00 pm"),
        ("2026-10-04 09:00", "domingo 4 de octubre, 9:00 am"),
        ("2027-03-14 08:00", "domingo 14 de marzo de 2027, 8:00 am"),
    ],
)
def test_fecha_larga_para_confirmaciones(now, when, expected):
    assert fmt.fecha_larga(local(when), TZ, now) == expected


def test_fecha_corta_cabe_en_un_boton_siempre(now):
    start = local("2026-10-03 00:00")
    for day in range(0, 900, 7):
        for hour in (0, 9, 12, 23):
            moment = start + timedelta(days=day, hours=hour)
            assert len(fmt.fecha_corta(moment, TZ, now)) <= fmt.MAX_LABEL, moment


# --- Botones -------------------------------------------------------------------------------------


def test_label_recorta_a_22_caracteres_con_puntos_suspensivos():
    assert fmt.MAX_LABEL == 22
    assert fmt.label("Tarea") == "Tarea"
    assert fmt.label("x" * 22) == "x" * 22
    long = fmt.label("Proyectos de la universidad y más")
    assert len(long) == 22 and long.endswith("…")


@pytest.mark.parametrize(
    ("count", "last_alone", "expected"),
    [
        (4, False, (2, 2)),
        (5, False, (2, 2, 1)),
        (1, False, (1,)),
        (5, True, (2, 2, 1)),
        (4, True, (2, 1, 1)),
        (2, True, (1, 1)),
        (1, True, (1,)),
        (0, False, ()),
    ],
)
def test_rows_layout_filas_de_2_y_cancelar_al_final(count, last_alone, expected):
    layout = fmt.rows_layout(count, last_alone=last_alone)
    assert layout == expected
    assert sum(layout) == count


# --- El aviso de recordatorio --------------------------------------------------------------------


def test_aviso_de_recordatorio_con_area():
    assert fmt.reminder_notice("llevar tarea", "universidad", False) == Html(
        "<b>llevar tarea</b>\n\nRecordatorio · universidad"
    )


def test_aviso_de_recordatorio_sin_area_omite_la_linea_de_area():
    assert fmt.reminder_notice("llevar tarea", None, False) == Html(
        "<b>llevar tarea</b>\n\nRecordatorio"
    )


def test_aviso_retrasado_lleva_la_cursiva_al_final():
    assert fmt.reminder_notice("x", "iglesia", True) == Html(
        "<b>x</b>\n\nRecordatorio · iglesia <i>(retrasado)</i>"
    )
    assert fmt.reminder_notice("x", None, True) == Html(
        "<b>x</b>\n\nRecordatorio <i>(retrasado)</i>"
    )


@pytest.mark.parametrize("text", HOSTILE)
def test_el_aviso_escapa_el_texto_y_el_area(text):
    notice = fmt.reminder_notice(text, text, True)
    assert html_problems(notice) == []
    assert text in fmt.plain(notice)


def test_la_distribucion_de_los_botones_del_aviso_es_2_por_2():
    assert fmt.REMINDER_LAYOUT == (2, 2)


# --- Confirmaciones y avisos ---------------------------------------------------------------------


def test_linea_de_estado_con_la_palabra_en_negrita():
    assert fmt.state_line("Hecho", "llevar tarea") == Html("<b>Hecho</b> · llevar tarea")
    assert fmt.state_line("Pospuesto", "x", "hoy, 3:40 pm") == Html(
        "<b>Pospuesto</b> · x · hoy, 3:40 pm"
    )


@pytest.mark.parametrize("text", HOSTILE)
def test_la_linea_de_estado_escapa(text):
    assert html_problems(fmt.state_line("Hecho", text, text)) == []


def test_aviso_general_tiene_un_solo_formato():
    assert fmt.aviso("Esa opción ya no está disponible.") == Html(
        "<b>Aviso</b> · Esa opción ya no está disponible."
    )
    assert fmt.STALE_CHOICE == fmt.aviso("Esa opción ya no está disponible.")
    assert fmt.UNKNOWN_COMMAND == fmt.aviso(
        "No conozco ese comando. Escribe /ayuda para ver los disponibles."
    )


# --- Puntuación, no pictogramas ------------------------------------------------------------------


def test_el_punto_medio_y_la_raya_son_puntuacion_normal():
    assert find_pictograms("· — – … « »") == []


# --- Etiquetas de botón con hora: siempre am/pm --------------------------------------------------


@pytest.mark.parametrize(
    ("day", "when", "expected"),
    [
        ("Hoy", "2026-10-03 18:00", "Hoy 6:00 pm"),
        ("Mañana", "2026-10-04 09:00", "Mañana 9:00 am"),
        ("Mañana", "2026-10-04 12:00", "Mañana 12:00 pm"),
        ("Hoy", "2026-10-04 00:30", "Hoy 12:30 am"),
        ("Mañana", "2026-10-04 23:59", "Mañana 11:59 pm"),
    ],
)
def test_etiqueta_con_hora_usa_am_pm_y_cabe_en_un_boton(day, when, expected):
    result = fmt.etiqueta_hora(day, local(when), TZ)
    assert result == expected
    assert len(result) <= fmt.MAX_LABEL


# --- Corte 3: piezas de las vistas (listas, secciones, pantallas) --------------------------------


def test_clip_acorta_con_puntos_suspensivos_y_junta_espacios():
    assert fmt.clip("hola   mundo") == "hola mundo"
    assert fmt.clip("x" * 100, 10) == "x" * 9 + "…"
    assert fmt.clip("corto", 10) == "corto"


def test_bullet_une_las_partes_con_punto_medio_y_salta_las_vacias():
    assert fmt.bullet("a", None, "b", "", "c") == Html("- a · b · c")


def test_numbered_numera_desde_uno():
    assert fmt.numbered(["a", "b"]) == Html("1. a\n2. b")


def test_section_pone_el_titulo_en_negrita_y_limita_con_un_resumen():
    assert fmt.section("Tareas", ["- a", "- b"]) == Html("<b>Tareas</b>\n- a\n- b")
    cut = fmt.section("Tareas", ["- a", "- b", "- c"], limit=2)
    assert fmt.plain(cut) == "Tareas\n- a\n- b\ny 1 más"


def test_screen_separa_los_bloques_con_una_linea_en_blanco_y_salta_los_vacios():
    assert fmt.screen("Hoy", "uno", None, "", "dos") == Html("<b>Hoy</b>\n\nuno\n\ndos")


@pytest.mark.parametrize("text", HOSTILE)
def test_las_piezas_de_las_vistas_escapan_el_texto(text):
    built = fmt.screen(
        text,
        fmt.section(text, [fmt.bullet(text, text)]),
        fmt.numbered([fmt.bullet(text)]),
    )
    assert html_problems(built) == []
    assert text in fmt.plain(built)


def test_pending_list_numera_pone_el_total_y_resume_las_que_faltan():
    rows = [fmt.PendingRow("uno", "uni", "hoy, 5:00 pm"), fmt.PendingRow("dos")]
    assert fmt.plain(fmt.pending_list(5, rows, None)) == (
        "Pendientes (5)\n\n1. uno · uni · hoy, 5:00 pm\n2. dos\n\n"
        "y 3 más: filtra por área (/pendientes nombre)"
    )
    assert fmt.plain(fmt.pending_list(2, rows, "uni")).startswith("Pendientes · uni (2)\n\n")
    assert fmt.pending_list(0, [], None, note="x") == Html(
        "<b>Pendientes (0)</b>\n\nNo tienes tareas pendientes. Todo al día.\n\nx"
    )


def test_pending_list_no_escapa_dos_veces():
    built = fmt.pending_list(1, [fmt.PendingRow("a & b <c>", "x&y", None)], None)
    assert html_problems(built) == []
    assert fmt.plain(built).endswith("1. a & b <c> · x&y")
    assert "&amp;amp;" not in built
