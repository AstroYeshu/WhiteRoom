"""Commit 2 del estilo: las listas de tareas van agrupadas por área (/pendientes y /hoy).

Reloj: sábado 2026-10-03 15:30 en México. Cada área con tareas abiertas es un encabezado en negrita
y debajo van sus tareas en una lista numerada con numeración continua; las áreas sin tareas no
aparecen; las tareas sin área van al final bajo «Sin área»; las áreas archivadas con tareas SÍ
se muestran (después de las activas). La agrupación (`formato.group_tasks`) es una función pura
y reutilizable (la usará «¿Quitas alguna?» de la Fase 3).
"""

from datetime import UTC, datetime, timedelta

import pytest

from asistente import formato as fmt
from asistente.choices import decode_choice_id
from asistente.core import areas, tasks
from tests.botkit import Bot, module_loop  # noqa: F401
from tests.htmlcheck import html_problems
from tests.test_commands import add_reminder, add_task, local
from tests.test_telegram_real import RealPath

TOAST = "Esa opción ya no aplica"


@pytest.fixture
def bot(conn, clock) -> Bot:
    return Bot(conn, clock)


def listing(bot: Bot, command: str = "/pendientes") -> str:
    """La lista tal como se ve (sin etiquetas): el último mensaje con botones, o el último."""
    bot.say(command)
    return fmt.plain(bot.channel.log[-1][1])


def new_area(conn, clock, name: str, archived: bool = False) -> areas.Area:
    created = areas.create_area(conn, name, "", clock)
    if archived:
        areas.archive_area(conn, created.id)
    return created


def task_ids(bot: Bot) -> dict[str, int]:
    """{número del botón: id de la tarea} de la lista que está en pantalla."""
    return {choice.label: int(decode_choice_id(choice.id)[1][-1]) for choice in bot.question[1]}


# --- La función pura: group_tasks -----------------------------------------------------------------

NOW = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)


def item(task_id, title="t", area=None, due_hours=None, created_minutes=0, when=None):
    due = NOW + timedelta(hours=due_hours) if due_hours is not None else None
    return fmt.TaskItem(task_id, title, area, due, NOW + timedelta(minutes=created_minutes), when)


AREAS = [fmt.AreaRef(1, "Universidad"), fmt.AreaRef(2, "Proyectos"), fmt.AreaRef(3, "Personal")]


def names(groups: fmt.TaskGroups) -> list[str | None]:
    return [group.area for group in groups.groups]


def ids(groups: fmt.TaskGroups) -> list[int]:
    return [one.id for one in groups.shown]


def test_un_area_sin_tareas_no_aparece():
    groups = fmt.group_tasks([item(1, area=3), item(2, area=1)], AREAS)
    assert names(groups) == ["Universidad", "Personal"]


def test_las_areas_siguen_el_orden_dado_no_el_de_las_tareas():
    items = [item(1, area=3), item(2, area=2), item(3, area=1)]
    assert names(fmt.group_tasks(items, AREAS)) == ["Universidad", "Proyectos", "Personal"]
    assert names(fmt.group_tasks(items, list(reversed(AREAS)))) == [
        "Personal",
        "Proyectos",
        "Universidad",
    ]


def test_las_tareas_sin_area_van_al_final_bajo_none():
    groups = fmt.group_tasks([item(1), item(2, area=3), item(3)], AREAS)
    assert names(groups) == ["Personal", None]
    assert [one.id for one in groups.groups[-1].items] == [1, 3]


def test_un_area_desconocida_cuenta_como_sin_area():
    groups = fmt.group_tasks([item(1, area=99), item(2, area=1)], AREAS)
    assert names(groups) == ["Universidad", None]


def test_dentro_del_area_vencidas_primero_luego_por_fecha_y_al_final_sin_fecha():
    items = [
        item(1, area=1),  # sin fecha, creada primero
        item(2, area=1, due_hours=30),
        item(3, area=1, due_hours=-20),  # vencida hace 20 h
        item(4, area=1, due_hours=2),
        item(5, area=1, due_hours=-50),  # vencida hace 50 h
        item(6, area=1, created_minutes=-10),  # sin fecha, creada ANTES que la 1
    ]
    assert ids(fmt.group_tasks(items, AREAS)) == [5, 3, 4, 2, 6, 1]


def test_con_la_misma_fecha_desempata_la_creacion_y_luego_el_id():
    items = [
        item(9, area=1, due_hours=5, created_minutes=3),
        item(8, area=1, due_hours=5, created_minutes=3),
        item(7, area=1, due_hours=5, created_minutes=1),
    ]
    assert ids(fmt.group_tasks(items, AREAS)) == [7, 8, 9]


def test_el_resultado_no_depende_del_orden_de_entrada():
    items = [item(1, area=2), item(2, area=1, due_hours=1), item(3), item(4, area=1)]
    first = fmt.group_tasks(items, AREAS)
    second = fmt.group_tasks(list(reversed(items)), AREAS)
    assert first == second


def test_el_limite_corta_siempre_el_final_del_orden():
    items = [item(number, area=1) for number in range(1, 9)]
    items += [item(number, area=3) for number in range(9, 17)]
    groups = fmt.group_tasks(items, AREAS, limit=15)
    assert groups.total == 16 and groups.hidden == 1
    assert ids(groups) == list(range(1, 16))


def test_un_area_cuyas_tareas_se_cortan_todas_pierde_el_encabezado():
    items = [item(number, area=1) for number in range(1, 16)] + [item(99, area=3)]
    groups = fmt.group_tasks(items, AREAS, limit=15)
    assert names(groups) == ["Universidad"] and groups.hidden == 1


def test_sin_tareas_no_hay_grupos():
    groups = fmt.group_tasks([], AREAS)
    assert groups.groups == () and groups.total == 0 and groups.hidden == 0


def test_la_funcion_no_modifica_lo_que_recibe():
    items = [item(2, area=1), item(1, area=1)]
    snapshot = list(items)
    fmt.group_tasks(items, AREAS)
    assert items == snapshot


def test_el_limite_por_defecto_es_15():
    assert fmt.TASK_LIST_LIMIT == 15
    items = [item(number, area=1) for number in range(1, 21)]
    assert len(fmt.group_tasks(items, AREAS).shown) == 15


# --- /pendientes: encabezados y numeración continua -----------------------------------------------


def seed(conn, clock) -> None:
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_task(conn, clock, "estudiar", None, "universidad")
    add_task(conn, clock, "leer", "2026-10-02 09:00", "universidad")
    add_task(conn, clock, "regar plantas", "2026-10-04 09:00", "personal")
    add_task(conn, clock, "pagar luz", "2026-10-02 17:00")
    add_task(conn, clock, "comprar pan")


def test_pendientes_agrupa_por_area_con_numeracion_continua(bot, conn, clock):
    seed(conn, clock)
    assert listing(bot) == (
        "Pendientes (6)\n\n"
        "Universidad\n"
        "1. Leer · venció vie 2 oct\n"
        "2. Entregar informe · hoy, 5:00 pm\n"
        "3. Estudiar\n\n"
        "Personal\n"
        "4. Regar plantas · mañana, 9:00 am\n\n"
        "Sin área\n"
        "5. Pagar luz · venció vie 2 oct\n"
        "6. Comprar pan"
    )


def test_los_encabezados_van_en_negrita(bot, conn, clock):
    seed(conn, clock)
    bot.say("/pendientes")
    html = bot.channel.log[-1][1]
    assert "<b>Universidad</b>\n1. Leer" in html
    assert "<b>Personal</b>\n4. Regar" in html
    assert "<b>Sin área</b>\n5. Pagar" in html
    assert "<b>Pendientes (6)</b>" in html
    assert html_problems(html) == []


def test_las_areas_sin_tareas_no_aparecen(bot, conn, clock):
    add_task(conn, clock, "regar plantas", None, "personal")
    text = listing(bot)
    assert text == "Pendientes (1)\n\nPersonal\n1. Regar plantas"
    for empty in ("Universidad", "Proyectos", "Iglesia", "Sin área"):
        assert empty not in text


def test_las_tareas_sin_area_van_al_final_bajo_sin_area(bot, conn, clock):
    add_task(conn, clock, "suelta")
    add_task(conn, clock, "regar plantas", None, "personal")
    add_task(conn, clock, "otra suelta")
    assert listing(bot) == (
        "Pendientes (3)\n\nPersonal\n1. Regar plantas\n\nSin área\n2. Suelta\n3. Otra suelta"
    )


def test_solo_tareas_sin_area_llevan_su_encabezado(bot, conn, clock):
    add_task(conn, clock, "suelta")
    assert listing(bot) == "Pendientes (1)\n\nSin área\n1. Suelta"


def test_un_area_archivada_con_tareas_abiertas_se_muestra_despues_de_las_activas(bot, conn, clock):
    old = new_area(conn, clock, "Antigua", archived=True)
    new_area(conn, clock, "Arte")
    tasks.create_task(conn, "de antes", clock, area_id=old.id)
    add_task(conn, clock, "dibujar", None, "arte")
    add_task(conn, clock, "regar plantas", None, "personal")
    add_task(conn, clock, "suelta")
    assert listing(bot) == (
        "Pendientes (4)\n\n"
        "Personal\n1. Regar plantas\n\n"
        "Arte\n2. Dibujar\n\n"
        "Antigua\n3. De antes\n\n"
        "Sin área\n4. Suelta"
    )


def test_un_area_archivada_sin_tareas_no_aparece(bot, conn, clock):
    new_area(conn, clock, "Antigua", archived=True)
    add_task(conn, clock, "suelta")
    assert "Antigua" not in listing(bot)


def test_el_orden_de_las_areas_es_el_de_areas(bot, conn, clock):
    new_area(conn, clock, "Arte")
    add_task(conn, clock, "dibujar", None, "arte")
    add_task(conn, clock, "regar plantas", None, "personal")
    add_task(conn, clock, "estudiar", None, "universidad")
    listed = fmt.plain(bot.reply("/areas"))
    order = [line[2:].partition(" · ")[0] for line in listed.splitlines() if line.startswith("- ")]
    assert order == ["Universidad", "Proyectos", "Iglesia", "Personal", "Arte"]
    text = listing(bot)
    assert [name for name in order if name in text] == ["Universidad", "Personal", "Arte"]
    assert text.index("Universidad") < text.index("Personal") < text.index("Arte")


def test_el_orden_de_las_tareas_no_depende_de_cuando_se_crearon_las_areas(bot, conn, clock):
    add_task(conn, clock, "tercera", None, "personal")
    add_task(conn, clock, "primera", None, "universidad")
    assert listing(bot) == ("Pendientes (2)\n\nUniversidad\n1. Primera\n\nPersonal\n2. Tercera")


def test_pendientes_dentro_del_area_vencidas_primero_luego_fecha_y_sin_fecha(bot, conn, clock):
    add_task(conn, clock, "sin fecha uno", None, "personal")
    add_task(conn, clock, "mañana", "2026-10-04 09:00", "personal")
    add_task(conn, clock, "vencida", "2026-10-01 09:00", "personal")
    add_task(conn, clock, "hoy", "2026-10-03 18:00", "personal")
    add_task(conn, clock, "sin fecha dos", None, "personal")
    assert listing(bot) == (
        "Pendientes (5)\n\nPersonal\n"
        "1. Vencida · venció jue 1 oct\n"
        "2. Hoy · hoy, 6:00 pm\n"
        "3. Mañana · mañana, 9:00 am\n"
        "4. Sin fecha uno\n"
        "5. Sin fecha dos"
    )


def test_ya_no_se_repite_el_area_en_cada_linea(bot, conn, clock):
    seed(conn, clock)
    lines = [line for line in listing(bot).splitlines() if line[:1].isdigit()]
    assert len(lines) == 6
    for line in lines:
        assert "Universidad" not in line and "Personal" not in line


def test_las_tareas_cerradas_no_aparecen(bot, conn, clock):
    done = add_task(conn, clock, "ya hecha", None, "personal")
    tasks.mark_done(conn, done.id, clock)
    add_task(conn, clock, "regar plantas", None, "personal")
    assert listing(bot) == "Pendientes (1)\n\nPersonal\n1. Regar plantas"


def test_sin_tareas_el_estado_vacio_no_cambia(bot):
    assert listing(bot) == "Pendientes (0)\n\nNo tienes tareas pendientes. Todo al día."


# --- Botones: un botón por número, con el id de la tarea ------------------------------------------


def test_cada_boton_conserva_el_id_de_su_tarea_con_numeracion_continua(bot, conn, clock):
    first = add_task(conn, clock, "primera", None, "personal")
    second = add_task(conn, clock, "segunda", None, "universidad")
    third = add_task(conn, clock, "tercera")
    fourth = add_task(conn, clock, "cuarta", None, "universidad")
    bot.say("/pendientes")
    assert bot.labels() == ["1", "2", "3", "4"]
    # orden: Universidad (segunda, cuarta), Personal (primera), Sin área (tercera)
    assert task_ids(bot) == {"1": second.id, "2": fourth.id, "3": first.id, "4": third.id}


def test_un_numero_abre_la_tarea_correcta_aunque_este_en_otro_grupo(bot, conn, clock):
    add_task(conn, clock, "primera", None, "personal")
    add_task(conn, clock, "segunda", None, "universidad")
    bot.say("/pendientes")
    bot.tap("2")
    assert fmt.plain(bot.question[0]).startswith("Primera\n\nÁrea: Personal")
    assert bot.labels() == ["Hecha", "Descartar", "Volver"]


def test_los_numeros_van_de_5_en_5_con_10_o_mas_tareas(bot, conn, clock):
    for count, layout in ((10, (5, 5)), (12, (5, 5, 2)), (15, (5, 5, 5))):
        with conn:
            conn.execute("DELETE FROM tasks")
        for number in range(count):
            add_task(conn, clock, f"tarea {number}", None, "personal")
        bot.say("/pendientes")
        assert bot.channel.layouts[-1] == layout, count
        assert bot.labels() == [str(n) for n in range(1, count + 1)]


def test_con_menos_de_10_tareas_los_numeros_tambien_van_de_5_en_5(bot, conn, clock):
    for number in range(9):
        add_task(conn, clock, f"tarea {number}", None, "personal")
    bot.say("/pendientes")
    assert bot.channel.layouts[-1] == (5, 4)


# --- Filtro por área: sin encabezados -------------------------------------------------------------


def test_con_filtro_no_hay_encabezados_y_el_titulo_lleva_el_area_y_el_total(bot, conn, clock):
    seed(conn, clock)
    assert listing(bot, "/pendientes universidad") == (
        "Pendientes · Universidad (3)\n\n"
        "1. Leer · venció vie 2 oct\n"
        "2. Entregar informe · hoy, 5:00 pm\n"
        "3. Estudiar"
    )


def test_el_filtro_acepta_otra_capitalizacion_y_acentos(bot, conn, clock):
    add_task(conn, clock, "regar plantas", None, "personal")
    for typed in ("personal", "PERSONAL", "Pérsonal"):
        assert listing(bot, f"/pendientes {typed}") == (
            "Pendientes · Personal (1)\n\n1. Regar plantas"
        )


def test_con_filtro_los_botones_siguen_el_orden_de_la_lista(bot, conn, clock):
    first = add_task(conn, clock, "sin fecha", None, "universidad")
    second = add_task(conn, clock, "con fecha", "2026-10-04 09:00", "universidad")
    add_task(conn, clock, "ajena", None, "personal")
    bot.say("/pendientes universidad")
    assert task_ids(bot) == {"1": second.id, "2": first.id}
    bot.tap("1")
    assert fmt.plain(bot.question[0]).startswith("Con fecha")


def test_un_area_que_no_existe_da_el_mismo_aviso(bot):
    assert listing(bot, "/pendientes nada") == (
        "Aviso · No encuentro el área «nada». Escribe /areas para ver las que hay."
    )


def test_un_area_existente_sin_tareas_da_el_estado_vacio_con_el_area(bot):
    assert listing(bot, "/pendientes proyectos") == (
        "Pendientes · Proyectos (0)\n\nNo tienes tareas pendientes. Todo al día."
    )


# --- Límite de 15 ---------------------------------------------------------------------------------


def test_con_16_tareas_se_muestran_15_y_se_dice_cuantas_faltan(bot, conn, clock):
    for number in range(1, 17):
        add_task(conn, clock, f"tarea {number:02d}", None, "personal")
    bot.say("/pendientes")
    text = fmt.plain(bot.channel.log[-1][1])
    assert text.startswith("Pendientes (16)\n\nPersonal\n1. Tarea 01\n")
    assert "15. Tarea 15" in text and "16." not in text and "Tarea 16" not in text
    assert text.endswith("\n\ny 1 más: filtra por área (/pendientes nombre)")
    assert bot.labels() == [str(n) for n in range(1, 16)]
    assert bot.channel.layouts[-1] == (5, 5, 5)


def test_con_exactamente_15_no_hay_pie(bot, conn, clock):
    for number in range(15):
        add_task(conn, clock, f"tarea {number:02d}", None, "personal")
    assert "más" not in listing(bot)


def test_lo_que_se_corta_es_el_final_del_orden_estable_y_no_lo_primero(bot, conn, clock):
    for number in range(1, 9):
        add_task(conn, clock, f"uni {number}", None, "universidad")
    for number in range(1, 9):
        add_task(conn, clock, f"per {number}", None, "personal")
    text = listing(bot)
    assert "8. Uni 8" in text and "15. Per 7" in text
    assert "Per 8" not in text
    assert text.endswith("y 1 más: filtra por área (/pendientes nombre)")


def test_un_area_cuyas_tareas_se_cortan_todas_no_deja_su_encabezado(bot, conn, clock):
    for number in range(1, 16):
        add_task(conn, clock, f"uni {number:02d}", None, "universidad")
    add_task(conn, clock, "per", None, "personal")
    text = listing(bot)
    assert "Personal" not in text and "Universidad" in text
    assert text.startswith("Pendientes (16)")
    assert text.endswith("y 1 más: filtra por área (/pendientes nombre)")


def test_el_limite_tambien_rige_con_filtro(bot, conn, clock):
    for number in range(16):
        add_task(conn, clock, f"tarea {number:02d}", None, "personal")
    text = listing(bot, "/pendientes personal")
    assert text.startswith("Pendientes · Personal (16)\n\n1. Tarea 00")
    assert "15. Tarea 14" in text and "Tarea 15" not in text
    assert text.endswith("\n\ny 1 más")  # con filtro ya activo no sugiere filtrar


# --- Escape: nombres de área y textos del usuario -------------------------------------------------


def test_el_nombre_del_area_y_el_titulo_se_escapan(bot, conn, clock):
    new_area(conn, clock, "r&d <x>")
    add_task(conn, clock, "<b>t</b> & x", None, "r&d <x>")
    bot.say("/pendientes")
    html = bot.channel.log[-1][1]
    assert "<b>R&amp;d &lt;x&gt;</b>\n1. &lt;b&gt;t&lt;/b&gt; &amp; x" in html
    assert "<b>t</b>" not in html and "<x>" not in html
    assert html_problems(html) == []


def test_el_nombre_del_area_se_escapa_tambien_en_el_titulo_con_filtro(bot, conn, clock):
    new_area(conn, clock, "r&d <x>")
    add_task(conn, clock, "t", None, "r&d <x>")
    bot.say("/pendientes r&d <x>")
    html = bot.channel.log[-1][1]
    assert "<b>Pendientes · R&amp;d &lt;x&gt; (1)</b>" in html
    assert html_problems(html) == []


@pytest.mark.parametrize(
    "hostile", ["<b>negrita</b>", "a < b > c & d", "</b></i></code> <code>", "&lt;ya escapado&gt;"]
)
def test_la_lista_pura_escapa_cualquier_texto_hostil(hostile):
    groups = fmt.group_tasks(
        [item(1, title=hostile, area=1, when=hostile), item(2, title=hostile)],
        [fmt.AreaRef(1, hostile)],
    )
    built = fmt.pending_list(groups, None)
    assert html_problems(built) == []
    assert "&amp;amp;" not in built
    assert fmt.cap_first(hostile) in fmt.plain(built)


# --- Tras una acción: la lista vuelve actualizada -------------------------------------------------


def test_hecha_vuelve_a_la_lista_con_la_numeracion_recalculada(bot, conn, clock):
    add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "universidad")
    add_task(conn, clock, "tres", None, "personal")
    bot.say("/pendientes")
    bot.tap("2")
    bot.tap("Hecha")
    assert fmt.plain(bot.question[0]) == (
        "Pendientes (2)\n\nUniversidad\n1. Uno\n\nPersonal\n2. Tres\n\nHecha · Dos"
    )
    assert bot.labels() == ["1", "2"]
    assert bot.sent_count() == 1


def test_descartar_vuelve_a_la_lista_y_si_se_vacia_un_area_su_encabezado_desaparece(
    bot, conn, clock
):
    add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "personal")
    bot.say("/pendientes")
    bot.tap("1")
    bot.tap("Descartar")
    assert fmt.plain(bot.question[0]) == "Pendientes (1)\n\nPersonal\n1. Dos\n\nDescartada · Uno"
    assert "Universidad" not in fmt.plain(bot.question[0]).split("\n\n")[1]


def test_hecha_con_filtro_conserva_el_filtro_y_los_numeros(bot, conn, clock):
    add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "universidad")
    add_task(conn, clock, "ajena", None, "personal")
    bot.say("/pendientes universidad")
    bot.tap("1")
    bot.tap("Hecha")
    assert fmt.plain(bot.question[0]) == "Pendientes · Universidad (1)\n\n1. Dos\n\nHecha · Uno"


def test_volver_muestra_la_lista_agrupada(bot, conn, clock):
    add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "personal")
    bot.say("/pendientes")
    bot.tap("2")
    bot.tap("Volver")
    assert fmt.plain(bot.question[0]) == (
        "Pendientes (2)\n\nUniversidad\n1. Uno\n\nPersonal\n2. Dos"
    )


def test_un_numero_de_una_lista_vieja_abre_la_tarea_por_su_id(bot, conn, clock):
    add_task(conn, clock, "uno", None, "universidad")
    gone = add_task(conn, clock, "dos", None, "universidad")
    add_task(conn, clock, "tres", None, "personal")
    bot.say("/pendientes")
    old = {number: choice_id for number, choice_id in bot.buttons_of("Pendientes").items()}
    tasks.mark_done(conn, gone.id, clock)  # desde otro lado: la lista en pantalla quedó vieja
    toast = bot.press(old["3"])  # en la lista nueva el 3 ya no existe; en la vieja era «Tres»
    assert toast is None
    assert fmt.plain(bot.question[0]).startswith("Tres\n\nÁrea: Personal")


def test_un_numero_de_una_lista_vieja_de_una_tarea_cerrada_da_aviso_y_actualiza(bot, conn, clock):
    add_task(conn, clock, "uno", None, "universidad")
    gone = add_task(conn, clock, "dos", None, "universidad")
    add_task(conn, clock, "tres", None, "personal")
    bot.say("/pendientes")
    old = bot.buttons_of("Pendientes")
    tasks.mark_done(conn, gone.id, clock)
    toast = bot.press(old["2"])
    assert toast == TOAST
    assert fmt.plain(bot.question[0]) == (
        "Pendientes (2)\n\nUniversidad\n1. Uno\n\nPersonal\n2. Tres"
    )
    assert bot.labels() == ["1", "2"]


def test_pulsar_hecha_dos_veces_da_aviso_y_la_lista_sigue_correcta(bot, conn, clock):
    add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "personal")
    bot.say("/pendientes")
    bot.tap("1")
    done = bot.choice_id("Hecha")
    bot.press(done)
    assert bot.press(done) == TOAST
    assert fmt.plain(bot.question[0]).startswith("Pendientes (1)\n\nPersonal\n1. Dos")


# --- /hoy: la sección Tareas va agrupada; los recordatorios no cambian ----------------------------


def seed_today(conn, clock) -> None:
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    add_task(conn, clock, "leer", "2026-10-02 09:00", "universidad")
    add_task(conn, clock, "pagar luz", "2026-10-02 17:00")
    add_task(conn, clock, "regar plantas", "2026-10-03 20:00", "personal")
    add_task(conn, clock, "de mañana", "2026-10-04 09:00", "personal")
    add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00", "personal")
    add_reminder(conn, clock, "gimnasio", "2026-10-03 16:00")


def test_hoy_agrupa_las_tareas_por_area_y_deja_los_recordatorios_en_orden_cronologico(
    bot, conn, clock
):
    seed_today(conn, clock)
    assert listing(bot, "/hoy") == (
        "Hoy · sábado 3 de octubre\n\n"
        "Tareas\n"
        "Universidad\n"
        "- Leer · vencida vie 2 oct, 9:00 am\n"
        "- Entregar informe · hoy, 5:00 pm\n\n"
        "Personal\n"
        "- Regar plantas · hoy, 8:00 pm\n\n"
        "Sin área\n"
        "- Pagar luz · vencida vie 2 oct, 5:00 pm\n\n"
        "Recordatorios\n"
        "- hoy, 4:00 pm · Gimnasio\n"
        "- hoy, 6:00 pm · Llamar a mamá · Personal\n\n"
        "1 en bandeja sin área"
    )


def test_hoy_los_encabezados_van_en_negrita(bot, conn, clock):
    seed_today(conn, clock)
    bot.say("/hoy")
    html = bot.channel.log[-1][1]
    assert "<b>Tareas</b>\n<b>Universidad</b>\n- Leer" in html
    assert "<b>Sin área</b>\n- Pagar luz" in html
    assert html_problems(html) == []


def test_hoy_con_filtro_no_hay_encabezados_de_area(bot, conn, clock):
    seed_today(conn, clock)
    text = listing(bot, "/hoy universidad")
    assert text == (
        "Hoy · sábado 3 de octubre · Universidad\n\n"
        "Tareas\n"
        "- Leer · vencida vie 2 oct, 9:00 am\n"
        "- Entregar informe · hoy, 5:00 pm"
    )


def test_hoy_sin_tareas_no_muestra_la_seccion(bot, conn, clock):
    add_reminder(conn, clock, "llamar a mamá", "2026-10-03 18:00")
    text = listing(bot, "/hoy")
    assert "Tareas" not in text and text.startswith("Hoy · sábado 3 de octubre\n\nRecordatorios")


def test_hoy_limita_las_tareas_a_15_con_el_pie_de_hoy(bot, conn, clock):
    for number in range(17):
        add_task(conn, clock, f"tarea {number:02d}", "2026-10-03 17:00", "personal")
    text = listing(bot, "/hoy")
    assert "- Tarea 14" in text and "Tarea 15" not in text
    assert "y 2 más: filtra por área (/hoy nombre)" in text


def test_hoy_escapa_el_area_y_el_titulo(bot, conn, clock):
    new_area(conn, clock, "r&d <x>")
    add_task(conn, clock, "<b>t</b> & x", "2026-10-03 17:00", "r&d <x>")
    bot.say("/hoy")
    html = bot.channel.log[-1][1]
    assert "<b>R&amp;d &lt;x&gt;</b>\n- &lt;b&gt;t&lt;/b&gt; &amp; x" in html
    assert html_problems(html) == []


def test_hoy_un_area_archivada_con_tareas_se_muestra(bot, conn, clock):
    old = new_area(conn, clock, "Antigua", archived=True)
    tasks.create_task(conn, "de antes", clock, area_id=old.id)
    with conn:
        conn.execute("UPDATE tasks SET due_at_utc = '2026-10-03T23:00:00+00:00'")
    assert "Antigua\n- De antes · hoy, 5:00 pm" in listing(bot, "/hoy")


# --- Con la librería REAL (Update.de_json) --------------------------------------------------------


def _rows(call: dict) -> list[list[dict]]:
    return [[button.to_dict() for button in row] for row in call["reply_markup"].inline_keyboard]


def test_real_la_lista_agrupada_y_sus_botones(conn, clock, monkeypatch):
    add_task(conn, clock, "primera", None, "personal")
    second = add_task(conn, clock, "segunda", None, "universidad")
    real = RealPath(conn, monkeypatch)
    real.say("/pendientes")
    sent = real.sends[-1]
    assert sent["text"] == (
        "<b>Pendientes (2)</b>\n\n<b>Universidad</b>\n1. Segunda\n\n<b>Personal</b>\n2. Primera"
    )
    [row] = _rows(sent)
    assert [button["text"] for button in row] == ["1", "2"]
    assert row[0]["callback_data"] == f"pd:o:0:{second.id}"
    real.press(row[0]["callback_data"])
    assert real.edits[-1]["text"].startswith("<b>Segunda</b>")
    assert "Área: Universidad" in real.edits[-1]["text"]


def test_real_hecha_vuelve_a_la_lista_con_la_numeracion_nueva(conn, clock, monkeypatch):
    add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "personal")
    real = RealPath(conn, monkeypatch)
    real.say("/pendientes")
    [row] = _rows(real.sends[-1])
    real.press(row[0]["callback_data"])
    done = next(
        button["callback_data"]
        for line in _rows(real.edits[-1])
        for button in line
        if button["text"] == "Hecha"
    )
    real.press(done)
    assert real.edits[-1]["text"].startswith("<b>Pendientes (1)</b>\n\n<b>Personal</b>\n1. Dos")
    assert real.answers[-1]["text"] is None


def test_real_un_boton_de_una_tarea_cerrada_da_el_aviso_breve(conn, clock, monkeypatch):
    gone = add_task(conn, clock, "uno", None, "universidad")
    add_task(conn, clock, "dos", None, "personal")
    real = RealPath(conn, monkeypatch)
    real.say("/pendientes")
    [row] = _rows(real.sends[-1])
    tasks.mark_done(conn, gone.id, lambda: datetime(2026, 10, 3, 21, 30, tzinfo=UTC))
    real.press(row[0]["callback_data"])
    assert real.answers[-1]["text"] == TOAST
    assert real.edits[-1]["text"].startswith("<b>Pendientes (1)</b>\n\n<b>Personal</b>\n1. Dos")


def test_real_hoy_agrupado(conn, clock, monkeypatch):
    add_task(conn, clock, "entregar informe", "2026-10-03 17:00", "universidad")
    real = RealPath(conn, monkeypatch)
    real.say("/hoy")
    assert "<b>Tareas</b>\n<b>Universidad</b>\n- Entregar informe" in real.sends[-1]["text"]


# --- Reutilizable: la misma función sirve a otros llamadores --------------------------------------


def test_la_agrupacion_acepta_cualquier_llamador_sin_base_ni_reloj():
    groups = fmt.group_tasks(
        [item(5, "a", 1, when="hoy"), item(6, "b", 3), item(7, "c")],
        [fmt.AreaRef(1, "Universidad"), fmt.AreaRef(3, "Personal")],
    )
    assert fmt.plain(fmt.task_list_block(groups, headers=True)) == (
        "Universidad\n1. A · hoy\n\nPersonal\n2. B\n\nSin área\n3. C"
    )
    assert fmt.plain(fmt.task_list_block(groups, headers=False)) == "1. A · hoy\n2. B\n3. C"
    assert [one.id for one in groups.shown] == [5, 6, 7]


def test_hoy_las_areas_archivadas_van_despues_de_las_activas(bot, conn, clock):
    old = new_area(conn, clock, "Antigua", archived=True)
    new_area(conn, clock, "Arte")
    tasks.create_task(conn, "de antes", clock, area_id=old.id)
    add_task(conn, clock, "dibujar", None, "arte")
    with conn:
        conn.execute("UPDATE tasks SET due_at_utc = '2026-10-03T23:00:00+00:00'")
    text = listing(bot, "/hoy")
    assert text.index("Arte\n- Dibujar") < text.index("Antigua\n- De antes")


# --- Vencidas marcadas, pie según el filtro y /hoy con viñetas -----------------------------------


def test_fecha_vencida_es_solo_el_dia(clock):
    def when(text: str) -> str:
        return fmt.fecha_vencida(local(text), "America/Mexico_City", clock)

    assert when("2026-10-02 17:00") == "vie 2 oct"
    assert when("2026-10-03 13:00") == "hoy"
    assert when("2026-09-20 09:00") == "dom 20 sep"
    assert when("2025-03-14 09:00") == "14 mar 2025"


def test_pendientes_marca_lo_vencido_en_cada_linea(bot, conn, clock):
    add_task(conn, clock, "vencida ayer", "2026-10-02 17:00", "personal")
    add_task(conn, clock, "vencida hoy", "2026-10-03 13:00", "personal")
    add_task(conn, clock, "de hoy", "2026-10-03 17:00", "personal")
    add_task(conn, clock, "de mañana", "2026-10-04 09:00", "personal")
    add_task(conn, clock, "sin fecha", None, "personal")
    assert listing(bot) == (
        "Pendientes (5)\n\nPersonal\n"
        "1. Vencida ayer · venció vie 2 oct\n"
        "2. Vencida hoy · venció hoy\n"
        "3. De hoy · hoy, 5:00 pm\n"
        "4. De mañana · mañana, 9:00 am\n"
        "5. Sin fecha"
    )


def test_pendientes_con_filtro_tambien_marca_lo_vencido(bot, conn, clock):
    add_task(conn, clock, "vencida", "2026-10-02 17:00", "personal")
    assert listing(bot, "/pendientes personal") == (
        "Pendientes · Personal (1)\n\n1. Vencida · venció vie 2 oct"
    )


def test_lo_vencido_es_justo_en_el_limite_del_momento(bot, conn, clock):
    add_task(conn, clock, "ahora mismo", "2026-10-03 15:30", "personal")
    add_task(conn, clock, "un minuto despues", "2026-10-03 15:31", "personal")
    text = listing(bot)
    assert "Ahora mismo · hoy, 3:30 pm" in text  # justo ahora todavía no está vencida
    assert "Un minuto despues · hoy, 3:31 pm" in text


def test_el_pie_sin_filtro_sugiere_filtrar_por_area(bot, conn, clock):
    for number in range(16):
        add_task(conn, clock, f"tarea {number:02d}", None, "personal")
    assert listing(bot).endswith("\n\ny 1 más: filtra por área (/pendientes nombre)")


def test_el_pie_con_filtro_solo_dice_cuantas_mas(bot, conn, clock):
    for number in range(17):
        add_task(conn, clock, f"tarea {number:02d}", None, "personal")
    text = listing(bot, "/pendientes personal")
    assert text.endswith("\n\ny 2 más")
    assert "filtra" not in text


def test_hoy_usa_vinetas_y_no_numeros(bot, conn, clock):
    seed_today(conn, clock)
    text = listing(bot, "/hoy")
    assert text == (
        "Hoy · sábado 3 de octubre\n\n"
        "Tareas\n"
        "Universidad\n"
        "- Leer · vencida vie 2 oct, 9:00 am\n"
        "- Entregar informe · hoy, 5:00 pm\n\n"
        "Personal\n"
        "- Regar plantas · hoy, 8:00 pm\n\n"
        "Sin área\n"
        "- Pagar luz · vencida vie 2 oct, 5:00 pm\n\n"
        "Recordatorios\n"
        "- hoy, 4:00 pm · Gimnasio\n"
        "- hoy, 6:00 pm · Llamar a mamá · Personal\n\n"
        "1 en bandeja sin área"
    )
    assert not any(line[:1].isdigit() and ". " in line[:4] for line in text.splitlines())


def test_hoy_con_filtro_usa_vinetas_sin_encabezados(bot, conn, clock):
    seed_today(conn, clock)
    assert listing(bot, "/hoy universidad") == (
        "Hoy · sábado 3 de octubre · Universidad\n\n"
        "Tareas\n"
        "- Leer · vencida vie 2 oct, 9:00 am\n"
        "- Entregar informe · hoy, 5:00 pm"
    )


def test_hoy_el_pie_sin_filtro_y_con_filtro(bot, conn, clock):
    for number in range(17):
        add_task(conn, clock, f"tarea {number:02d}", "2026-10-03 17:00", "personal")
    assert "y 2 más: filtra por área (/hoy nombre)" in listing(bot, "/hoy")
    filtered = listing(bot, "/hoy personal")
    assert "y 2 más" in filtered and "filtra" not in filtered


def test_hoy_no_numera_pero_sus_tareas_siguen_ordenadas_por_area_y_fecha(bot, conn, clock):
    seed_today(conn, clock)
    text = listing(bot, "/hoy")
    assert text.index("Leer") < text.index("Entregar informe") < text.index("Regar plantas")
    assert text.index("Regar plantas") < text.index("Pagar luz")


def test_la_lista_pura_con_numeracion_apagada_usa_el_guion():
    groups = fmt.group_tasks([item(1, "a", 1, when="hoy"), item(2, "b")], AREAS)
    assert fmt.plain(fmt.task_list_block(groups, headers=True, numbered=False)) == (
        "Universidad\n- A · hoy\n\nSin área\n- B"
    )
    assert fmt.plain(fmt.task_list_block(groups, headers=False, numbered=False)) == "- A · hoy\n- B"


def test_el_pie_puro_depende_del_filtro():
    groups = fmt.group_tasks([item(n, area=1) for n in range(1, 19)], AREAS)
    assert fmt.task_list_footer(groups, "/pendientes", filtered=False) == (
        "y 3 más: filtra por área (/pendientes nombre)"
    )
    assert fmt.task_list_footer(groups, "/pendientes", filtered=True) == "y 3 más"
    assert fmt.task_list_footer(fmt.group_tasks([item(1)], AREAS), "/hoy", filtered=False) is None


def test_pendientes_con_filtro_lo_que_vence_justo_ahora_no_esta_vencido(bot, conn, clock):
    add_task(conn, clock, "justo ahora", "2026-10-03 15:30", "personal")
    assert listing(bot, "/pendientes personal") == (
        "Pendientes · Personal (1)\n\n1. Justo ahora · hoy, 3:30 pm"
    )


def test_pendientes_lo_vencido_hace_horas_el_mismo_dia_dice_hoy(bot, conn, clock):
    add_task(conn, clock, "temprano", "2026-10-03 08:00", "personal")
    assert listing(bot, "/pendientes personal") == (
        "Pendientes · Personal (1)\n\n1. Temprano · venció hoy"
    )


def test_pendientes_lo_vencido_de_otro_anio_lleva_el_anio(bot, conn, clock):
    add_task(conn, clock, "antigua", "2025-03-14 09:00", "personal")
    assert listing(bot, "/pendientes") == (
        "Pendientes (1)\n\nPersonal\n1. Antigua · venció 14 mar 2025"
    )


def test_hoy_con_filtro_y_16_tareas_el_pie_es_solo_y_1_mas(bot, conn, clock):
    for number in range(16):
        add_task(conn, clock, f"tarea {number:02d}", "2026-10-03 17:00", "personal")
    assert listing(bot, "/hoy personal").endswith("- Tarea 14 · hoy, 5:00 pm\n\ny 1 más")


def test_hoy_sin_filtro_y_16_tareas_el_pie_sugiere_filtrar(bot, conn, clock):
    for number in range(16):
        add_task(conn, clock, f"tarea {number:02d}", "2026-10-03 17:00", "personal")
    assert listing(bot, "/hoy").endswith("y 1 más: filtra por área (/hoy nombre)")
