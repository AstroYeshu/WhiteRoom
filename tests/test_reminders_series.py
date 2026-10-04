"""Motor de recordatorios (5b): rrule sin deriva, recuperación tras caída, insistencia,
avisos de preparación y cascada al cerrar tareas.

Reloj inicial: sábado 2026-10-03 15:30 en México. Silencio: 22:00-07:00.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from asistente.channels.base import PermanentChannelError, TransientChannelError
from asistente.core import areas, reminders, tasks
from asistente.core.reminders import ReminderEngine
from asistente.timeutil import local_to_utc, to_utc_iso
from tests.fakes import ScriptedChannel

TZ = "America/Mexico_City"
USER = "42"
WEEKLY_SUNDAY = "FREQ=WEEKLY;BYDAY=SU"
SUNDAY_8PM = local_to_utc(datetime(2026, 10, 4, 20, 0), TZ)


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


@pytest.fixture
def channel() -> ScriptedChannel:
    return ScriptedChannel()


@pytest.fixture
def engine(conn, channel, clock) -> ReminderEngine:
    return ReminderEngine(conn, channel, USER, TZ, clock)


def tick(engine: ReminderEngine) -> int:
    return asyncio.run(engine.tick())


def row(conn, reminder_id: int):
    return reminders.get_reminder(conn, reminder_id)


def all_rows(conn) -> list[reminders.Reminder]:
    return [row(conn, r["id"]) for r in conn.execute("SELECT id FROM reminders ORDER BY id")]


def texts(channel: ScriptedChannel) -> list[str]:
    return [text for _, text, _, _ in channel.choices]


# --- 3. Semanal con rrule: sin deriva, sin duplicados, con snooze ---------------------------


def test_semanal_con_retrasos_y_snooze_no_deriva_ni_duplica(conn, clock, engine, channel):
    reminders.create_reminder(conn, "iglesia", SUNDAY_8PM, clock, rrule=WEEKLY_SUNDAY)
    expected_messages = 0

    for week in range(6):
        scheduled = SUNDAY_8PM + timedelta(weeks=week)
        clock.current = scheduled + timedelta(seconds=7 + 13 * week)  # cada tick llega distinto
        assert tick(engine) == 1
        expected_messages += 1

        pending = [r for r in all_rows(conn) if r.status == "pending"]
        assert [r.fire_at_utc for r in pending] == [to_utc_iso(scheduled + timedelta(weeks=1))]
        assert len(all_rows(conn)) == week + 2

        if week % 2 == 0:  # posponer el aviso ya enviado y dejar que vuelva a sonar
            current_id = week + 1
            assert reminders.snooze(conn, current_id, timedelta(minutes=10), clock) is not None
            clock.advance(minutes=10)
            assert tick(engine) == 1
            expected_messages += 1
            assert len(all_rows(conn)) == week + 2  # re-disparar la fila pospuesta NO crea otra
            pending = [r for r in all_rows(conn) if r.status == "pending"]
            assert [r.fire_at_utc for r in pending] == [to_utc_iso(scheduled + timedelta(weeks=1))]

    assert len(channel.choices) == expected_messages


def test_diario_sin_deriva(conn, clock, engine):
    start = local("2026-10-04 08:00")
    reminders.create_reminder(conn, "vitaminas", start, clock, rrule="FREQ=DAILY")
    for day in range(5):
        clock.current = start + timedelta(days=day, minutes=1, seconds=11)
        assert tick(engine) == 1
        newest = all_rows(conn)[-1]
        assert newest.fire_at_utc == to_utc_iso(start + timedelta(days=day + 1))


def test_una_serie_con_count_termina(conn, clock, engine):
    reminders.create_reminder(conn, "x", SUNDAY_8PM, clock, rrule="FREQ=WEEKLY;COUNT=1")
    clock.current = SUNDAY_8PM
    assert tick(engine) == 1
    assert len(all_rows(conn)) == 1  # no hay siguiente


def test_rrule_invalida_se_rechaza_al_crear(conn, clock):
    with pytest.raises(ValueError):
        reminders.create_reminder(conn, "x", SUNDAY_8PM, clock, rrule="FREQ=CADA_RATO")
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


def test_marcar_sent_e_insertar_la_siguiente_es_una_transaccion(
    conn, clock, engine, channel, monkeypatch
):
    reminders.create_reminder(conn, "x", SUNDAY_8PM, clock, rrule=WEEKLY_SUNDAY)
    clock.current = SUNDAY_8PM

    def boom(*args, **kwargs):
        raise RuntimeError("falla al calcular la siguiente")

    monkeypatch.setattr(reminders, "next_occurrence", boom)
    assert tick(engine) == 0  # no se da por enviado
    rows = all_rows(conn)
    assert [(r.status, r.last_fired_at) for r in rows] == [("pending", None)]  # nada quedó a medias
    assert len(rows) == 1

    monkeypatch.undo()
    assert tick(engine) == 1  # el siguiente tick lo completa (repetir es mejor que perder)
    assert [r.status for r in all_rows(conn)] == ["sent", "pending"]
    assert (
        len(channel.choices) == 2
    )  # entrega "al menos una vez": el primer intento ya había salido


def test_si_un_recordatorio_repetido_se_rinde_la_serie_continua(conn, clock, engine, channel):
    first = reminders.create_reminder(conn, "iglesia", SUNDAY_8PM, clock, rrule=WEEKLY_SUNDAY)
    channel.always_fail_with(PermanentChannelError("bot_blocked"))
    clock.current = SUNDAY_8PM
    tick(engine)
    assert row(conn, first.id).stopped is True
    following = all_rows(conn)[1]
    assert following.fire_at_utc == to_utc_iso(SUNDAY_8PM + timedelta(weeks=1))
    assert following.status == "pending" and following.stopped is False

    channel.always_fail_with(None)  # el dueño desbloquea el bot
    clock.current = SUNDAY_8PM + timedelta(weeks=1)
    assert tick(engine) == 1
    assert texts(channel) == ["⏰ iglesia"]  # la del domingo siguiente sí suena


def test_rendirse_tras_24_horas_tambien_deja_seguir_la_serie(conn, clock, engine, channel):
    first = reminders.create_reminder(
        conn, "x", SUNDAY_8PM, clock, rrule=WEEKLY_SUNDAY, priority=2
    )  # prioridad 2: el silencio nocturno no salta ticks
    channel.always_fail_with(TransientChannelError("telegram_down"))
    clock.current = SUNDAY_8PM
    while not row(conn, first.id).stopped:
        tick(engine)
        clock.advance(seconds=reminders.BACKOFF_CAP_SECONDS)
        assert clock() < SUNDAY_8PM + timedelta(hours=25)
    assert row(conn, first.id).stopped is True
    pending = [r for r in all_rows(conn) if r.status == "pending" and not r.stopped]
    assert [r.fire_at_utc for r in pending] == [to_utc_iso(SUNDAY_8PM + timedelta(weeks=1))]


# --- 5. Recuperación tras una caída ---------------------------------------------------------


def test_tras_una_caida_salen_todos_los_vencidos_retrasados_y_en_orden(
    conn, clock, engine, channel
):
    now = clock()
    for name, ahead in (("hace 3 días", timedelta(minutes=3)), ("hace 1 día", timedelta(hours=1))):
        reminders.create_reminder(conn, name, now + ahead, clock)
    reminders.create_reminder(conn, "hace 1 hora", now + timedelta(days=2, hours=22), clock)

    clock.advance(days=3)  # el proceso estuvo caído 3 días
    fresh_engine = ReminderEngine(conn, channel, USER, TZ, clock)  # "arranque"
    assert tick(fresh_engine) == 3
    assert texts(channel) == [
        "⏰ hace 3 días (retrasado)",
        "⏰ hace 1 día (retrasado)",
        "⏰ hace 1 hora (retrasado)",
    ]
    assert {r.status for r in all_rows(conn)} == {"sent"}


def test_semanal_vencido_hace_tres_semanas_envia_uno_y_deja_la_siguiente_en_el_futuro(
    conn, clock, channel
):
    reminders.create_reminder(conn, "iglesia", SUNDAY_8PM, clock, rrule=WEEKLY_SUNDAY)
    clock.current = SUNDAY_8PM + timedelta(weeks=3, hours=1)  # tras la caída: domingo 21:00
    fresh_engine = ReminderEngine(conn, channel, USER, TZ, clock)
    assert tick(fresh_engine) == 1
    assert texts(channel) == ["⏰ iglesia (retrasado)"]
    rows = all_rows(conn)
    assert len(rows) == 2  # sin ráfaga de las 3 que se perdieron
    assert rows[1].fire_at_utc == to_utc_iso(SUNDAY_8PM + timedelta(weeks=4))  # sin deriva


def test_recuperacion_dentro_del_silencio_espera_a_que_termine(conn, clock, channel):
    reminders.create_reminder(conn, "x", clock() + timedelta(minutes=1), clock)
    clock.current = local("2026-10-04 03:00")  # la caída termina de madrugada
    fresh_engine = ReminderEngine(conn, channel, USER, TZ, clock)
    assert tick(fresh_engine) == 0
    clock.current = local("2026-10-04 07:00")
    assert tick(fresh_engine) == 1
    assert texts(channel) == ["⏰ x (retrasado)"]


# --- 7. Insistencia (priority=2) ------------------------------------------------------------


def test_insistencia_cada_15_minutos_hasta_3_reenvios(conn, clock, engine, channel):
    created = reminders.create_reminder(
        conn, "urgente", clock() + timedelta(minutes=1), clock, priority=2
    )
    clock.advance(minutes=1)
    assert tick(engine) == 1  # el aviso inicial
    for _ in range(3):
        clock.advance(minutes=14, seconds=59)
        assert tick(engine) == 0
        clock.advance(seconds=1)
        assert tick(engine) == 1  # reenvío
    clock.advance(hours=2)
    assert tick(engine) == 0  # ya no insiste
    assert texts(channel) == ["⏰ urgente"] * 4  # el reenvío no se etiqueta "(retrasado)"
    assert row(conn, created.id).nag_count == 3


def test_hecho_detiene_la_insistencia(conn, clock, engine, channel):
    created = reminders.create_reminder(
        conn, "urgente", clock() + timedelta(minutes=1), clock, priority=2
    )
    clock.advance(minutes=1)
    tick(engine)
    clock.advance(minutes=15)
    tick(engine)
    assert reminders.mark_done(conn, created.id) is True
    clock.advance(hours=1)
    assert tick(engine) == 0
    assert len(channel.choices) == 2


def test_posponer_reinicia_la_insistencia(conn, clock, engine, channel):
    created = reminders.create_reminder(
        conn, "urgente", clock() + timedelta(minutes=1), clock, priority=2
    )
    clock.advance(minutes=1)
    tick(engine)
    clock.advance(minutes=15)
    tick(engine)  # un reenvío (nag_count = 1)
    reminders.snooze(conn, created.id, timedelta(hours=1), clock)
    assert row(conn, created.id).nag_count == 0
    clock.advance(hours=1)
    assert tick(engine) == 1
    clock.advance(minutes=15)
    assert tick(engine) == 1  # vuelve a insistir desde cero


def test_la_insistencia_atraviesa_el_silencio(conn, clock, engine, channel):
    clock.current = local("2026-10-03 21:50")
    reminders.create_reminder(conn, "urgente", local("2026-10-03 21:55"), clock, priority=2)
    clock.current = local("2026-10-03 21:55")
    assert tick(engine) == 1
    clock.current = local("2026-10-03 22:10")  # ya es hora de silencio
    assert tick(engine) == 1


def test_la_insistencia_de_una_serie_no_crea_mas_siguientes(conn, clock, engine):
    reminders.create_reminder(conn, "x", SUNDAY_8PM, clock, rrule=WEEKLY_SUNDAY, priority=2)
    clock.current = SUNDAY_8PM
    for _ in range(4):
        tick(engine)
        clock.advance(minutes=15)
    assert len(all_rows(conn)) == 2  # el original y UNA siguiente


# --- 8. Avisos de preparación ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("due_in", "expected_offsets"),
    [
        (timedelta(days=3), [timedelta(days=1), timedelta(hours=1)]),
        (timedelta(days=1, minutes=30), [timedelta(days=1), timedelta(hours=1)]),
        (timedelta(days=1), [timedelta(hours=1)]),  # el de 1 día cae justo ahora: ya no es futuro
        (timedelta(hours=5), [timedelta(hours=1)]),
        (timedelta(hours=1), []),
        (timedelta(minutes=30), []),
    ],
)
def test_preparacion_solo_si_la_hora_no_ha_pasado(conn, clock, due_in, expected_offsets):
    due = clock() + due_in
    task = tasks.create_task(conn, "entregar proyecto", clock, due_at_utc=due)
    created = all_rows(conn)
    assert [r.fire_at_utc for r in created] == [to_utc_iso(due - o) for o in expected_offsets]
    assert all(r.task_id == task.id and r.status == "pending" for r in created)


def test_preparacion_textos_area_y_envio(conn, clock, engine, channel):
    uni = areas.find_area_by_name(conn, "universidad")
    due = local("2026-10-06 17:00")
    tasks.create_task(conn, "entregar proyecto", clock, area_id=uni.id, due_at_utc=due)
    clock.current = due - timedelta(days=1)
    assert tick(engine) == 1
    clock.current = due - timedelta(hours=1)
    assert tick(engine) == 1
    assert texts(channel) == [
        "⏰ Mañana vence: entregar proyecto [universidad]",
        "⏰ En 1 hora vence: entregar proyecto [universidad]",
    ]


def test_sin_fecha_no_hay_avisos(conn, clock):
    tasks.create_task(conn, "sin fecha", clock)
    assert all_rows(conn) == []


def test_cambiar_la_fecha_rehace_los_avisos(conn, clock):
    task = tasks.create_task(conn, "t", clock, due_at_utc=clock() + timedelta(days=3))
    old_ids = [r.id for r in all_rows(conn)]
    new_due = clock() + timedelta(days=5)
    tasks.set_due(conn, task.id, new_due, clock)
    rows = all_rows(conn)
    assert [r.status for r in rows if r.id in old_ids] == ["cancelled", "cancelled"]
    live = [r for r in rows if r.status == "pending"]
    assert [r.fire_at_utc for r in live] == [
        to_utc_iso(new_due - timedelta(days=1)),
        to_utc_iso(new_due - timedelta(hours=1)),
    ]
    tasks.set_due(conn, task.id, None, clock)  # quitar la fecha: no queda ningún aviso vivo
    assert [r for r in all_rows(conn) if r.status == "pending"] == []


# --- 11. Cascada: cerrar una tarea cancela sus recordatorios ---------------------------------


def _task_with_reminders(conn, clock, title="t"):
    task = tasks.create_task(conn, title, clock, due_at_utc=clock() + timedelta(days=3))
    other = tasks.create_task(conn, "otra", clock, due_at_utc=clock() + timedelta(days=3))
    manual = reminders.create_reminder(conn, "a mano", clock() + timedelta(hours=1), clock)
    return task, other, manual


@pytest.mark.parametrize("close", ["done", "drop", "postpone"])
def test_cerrar_una_tarea_cancela_sus_recordatorios_pendientes(conn, clock, close):
    task, other, manual = _task_with_reminders(conn, clock)
    if close == "done":
        assert tasks.mark_done(conn, task.id, clock)
    elif close == "drop":
        assert tasks.drop_task(conn, task.id, clock)
    else:
        assert tasks.postpone_task(conn, task.id, clock() + timedelta(days=2), clock)
    by_task = {}
    for r in all_rows(conn):
        by_task.setdefault(r.task_id, []).append(r.status)
    assert by_task[task.id] == ["cancelled", "cancelled"]  # incluidos los de preparación
    assert by_task[other.id] == ["pending", "pending"]  # los de otras tareas no se tocan
    assert row(conn, manual.id).status == "pending"  # ni los sueltos


def test_la_cascada_respeta_el_historial_y_corta_la_insistencia(conn, clock, engine):
    task = tasks.create_task(conn, "t", clock)
    sent = reminders.create_reminder(
        conn, "ya avisado", clock() + timedelta(minutes=1), clock, task_id=task.id
    )
    nagging = reminders.create_reminder(
        conn, "insiste", clock() + timedelta(minutes=1), clock, task_id=task.id, priority=2
    )
    clock.advance(minutes=1)
    tick(engine)
    assert row(conn, sent.id).status == "sent" and row(conn, nagging.id).status == "sent"
    assert tasks.mark_done(conn, task.id, clock)
    assert row(conn, sent.id).status == "sent"  # el historial no cambia
    assert row(conn, nagging.id).status == "cancelled"  # y deja de insistir
    clock.advance(hours=1)
    assert tick(engine) == 0


def test_cerrar_una_tarea_ya_cerrada_no_vuelve_a_cancelar(conn, clock):
    task = tasks.create_task(conn, "t", clock)
    assert tasks.mark_done(conn, task.id, clock)
    late = reminders.create_reminder(
        conn, "creado después", clock() + timedelta(hours=1), clock, task_id=task.id
    )
    assert tasks.drop_task(conn, task.id, clock) is False
    assert row(conn, late.id).status == "pending"


def test_recordatorio_de_tarea_cancelada_no_suena(conn, clock, engine, channel):
    task = tasks.create_task(conn, "t", clock, due_at_utc=clock() + timedelta(hours=5))
    tasks.drop_task(conn, task.id, clock)
    clock.advance(hours=6)
    assert tick(engine) == 0
    assert not channel.sent_anything


# --- 12. Nunca en el pasado (preparación) ---------------------------------------------------


def test_la_preparacion_nunca_crea_recordatorios_en_el_pasado(conn, clock):
    tasks.create_task(conn, "vencida", clock, due_at_utc=clock() - timedelta(days=2))
    assert all_rows(conn) == []
