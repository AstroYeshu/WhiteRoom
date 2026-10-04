"""Imprime el catálogo de TODAS las pantallas que ve el usuario y lo guarda en docs/MENSAJES.md.

Maneja los manejadores REALES (`bot/handlers.py`) con un canal de grabación, una base en memoria y
un reloj fijo, así que cada pantalla es exactamente lo que se enviaría hoy. No usa red, secretos
ni el `.env`, y no toca ninguna base real.

Uso (desde la raíz del repositorio, con el entorno virtual activado):
    python scripts/show_messages.py
"""

# ruff: noqa: E501  (los textos del catálogo se leen mejor en una sola línea)
from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asistente import db  # noqa: E402
from asistente.bot import handlers  # noqa: E402
from asistente.bot.conversation import Conversation  # noqa: E402
from asistente.channels.base import Choice, IncomingChoice, IncomingMessage  # noqa: E402
from asistente.core import areas, reminders, tasks  # noqa: E402
from asistente.core.reminders import ReminderEngine  # noqa: E402
from asistente.formato import to_html  # noqa: E402
from asistente.timeutil import local_to_utc  # noqa: E402

TZ = "America/Mexico_City"
OWNER = 12345
REF = "77"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "MENSAJES.md"
START = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)  # sábado 3 de octubre de 2026, 15:30 en México

_runner = asyncio.Runner()


def run(coroutine):
    return _runner.run(coroutine)


def local(text: str) -> datetime:
    return local_to_utc(datetime.strptime(text, "%Y-%m-%d %H:%M"), TZ)


@dataclass
class Clock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@dataclass
class Recorder:
    """Canal que solo anota lo que se enviaría, ya como lo recibiría Telegram (HTML):
    ("texto"|"botones"|"edicion", texto, filas de etiquetas)."""

    log: list[tuple[str, str, list[list[str]]]] = field(default_factory=list)

    async def send_text(self, to: str, text: str, kind: str = "reply") -> None:
        self.log.append(("texto", to_html(text), []))

    async def send_choices(
        self,
        to: str,
        text: str,
        choices: list[Choice],
        kind: str = "reply",
        layout: Sequence[int] | None = None,
    ) -> None:
        sizes = tuple(layout) if layout is not None else (1,) * len(choices)
        labels = [choice.label for choice in choices]
        rows, start = [], 0
        for size in sizes:
            rows.append(labels[start : start + size])
            start += size
        self.log.append(("botones", to_html(text), rows))

    async def edit_text(self, to: str, message_ref: str, text: str) -> None:
        self.log.append(("edicion", to_html(text), []))


class Session:
    """Una conversación completa con su propia base, reloj y estado."""

    def __init__(self, start: datetime = START) -> None:
        self.conn = db.open_db(":memory:")
        self.clock = Clock(start)
        self.channel = Recorder()
        self.conversation = Conversation()
        self._choices: list[tuple[str, list[Choice]]] = []
        self.engine = ReminderEngine(self.conn, self._wrap(), str(OWNER), TZ, self.clock)

    # El canal grabador guarda solo etiquetas; los ids se piden al fabricar los botones.
    def _last_choices(self, text_part: str | None) -> list[Choice]:
        for text, choices in reversed(self.channel_choices):
            if text_part is None or text_part in text:
                return choices
        raise LookupError(f"ningún mensaje con botones contiene {text_part!r}")

    @property
    def channel_choices(self) -> list[tuple[str, list[Choice]]]:
        return self._choices

    def say(self, text: str) -> None:
        event = IncomingMessage("catalogo", str(OWNER), text)
        run(
            handlers.handle_message(
                event, self._wrap(), OWNER, self.conn, self.clock, TZ, self.conversation
            )
        )

    def press(self, choice_id: str) -> None:
        event = IncomingChoice("catalogo", str(OWNER), choice_id, REF)
        run(
            handlers.handle_choice(
                event, self._wrap(), OWNER, self.conn, self.clock, TZ, self.conversation
            )
        )

    def tap(self, label: str, in_message: str | None = None) -> None:
        choices = self._last_choices(in_message)
        exact = [c for c in choices if c.label == label]
        partial = [c for c in choices if label in c.label]
        found = exact or partial
        if len(found) != 1:
            raise LookupError(f"no hay un único botón «{label}»")
        self.press(found[0].id)

    def tick(self) -> None:
        run(self.engine.tick())

    def _wrap(self):
        return _Tee(self.channel, self._choices)


class _Tee:
    """Reparte lo enviado al grabador y recuerda los botones completos (con sus ids)."""

    def __init__(self, recorder: Recorder, choices: list[tuple[str, list[Choice]]]) -> None:
        self._recorder, self._choices = recorder, choices

    async def send_text(self, to, text, kind="reply"):
        await self._recorder.send_text(to, text, kind)

    async def send_choices(self, to, text, choices, kind="reply", layout=None):
        self._choices.append((text, list(choices)))
        await self._recorder.send_choices(to, text, choices, kind, layout)

    async def edit_text(self, to, message_ref, text):
        await self._recorder.edit_text(to, message_ref, text)


# --- Documento ---------------------------------------------------------------------------------


class Catalog:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.screens = 0

    def section(self, title: str, intro: str = "") -> None:
        self.lines += ["", f"## {title}", ""]
        if intro:
            self.lines += [intro, ""]

    def snap(self, session: Session, comment: str, action: Callable[[], object]) -> None:
        """Ejecuta `action` y anota todo lo que el bot envió como resultado."""
        mark = len(session.channel.log)
        action()
        entries = session.channel.log[mark:]
        assert entries, f"sin respuesta: {comment}"
        self.render(comment, entries)

    def render(self, comment: str, entries: list[tuple[str, str, list[list[str]]]]) -> None:
        blocks = []
        for kind, text, rows in entries:
            parts = ["(reemplaza el mensaje del botón)"] if kind == "edicion" else []
            parts.append(text)
            parts += ["".join(f"[{label}]" for label in row) for row in rows]
            blocks.append("\n".join(parts))
        self.screens += 1
        self.lines += [f"_{comment}_", "", "```text", "\n---\n".join(blocks), "```", ""]


def build() -> Catalog:
    cat = Catalog()
    cat.lines += [
        "# Catálogo de mensajes",
        "",
        "Generado por `python scripts/show_messages.py` con los manejadores reales, una base en memoria",
        "y un reloj fijo: **sábado 3 de octubre de 2026, 3:30 pm** (México). Las áreas son las iniciales",
        "(universidad, proyectos, iglesia, personal). Los textos se muestran como los recibe Telegram:",
        "HTML con solo `<b>`, `<i>` y `<code>` (la consola quita las etiquetas). Cada fila de botones",
        "va en una línea, como `[Etiqueta]`; `---` separa mensajes distintos de una misma respuesta.",
        "«(reemplaza el mensaje del botón)» es una edición: el texto sustituye al mensaje que llevaba",
        "los botones, sin teclado.",
        "No incluye la salida de `scripts/dev_remind_me.py` ni los errores de configuración del arranque.",
    ]
    bandeja(cat)
    preguntas_del_parser(cat)
    avisos(cat)
    hoy(cat)
    pendientes(cat)
    recordatorios(cat)
    recordar(cat)
    tarea(cat)
    nota(cat)
    areas_y_nuevaarea(cat)
    ayuda(cat)
    errores(cat)
    return cat


# --- Bandeja -----------------------------------------------------------------------------------


def bandeja(cat: Catalog) -> None:
    cat.section(
        "Bandeja (mensaje libre)",
        "Cualquier texto que no es un comando se guarda al instante como tarea sin área y se pregunta qué es.",
    )
    s = Session()
    cat.snap(s, "Mensaje libre: pregunta de tipo.", lambda: s.say("comprar leche"))
    cat.snap(
        s,
        "Se elige Tarea: la elección queda en el mensaje y llega la pregunta de área.",
        lambda: s.tap("Tarea"),
    )
    cat.snap(s, "Se elige un área: la tarea queda guardada.", lambda: s.tap("personal"))

    s = Session()
    s.say("comprar leche")
    cat.snap(
        s,
        "Cancelar en cualquier pregunta: la tarea sigue en la bandeja.",
        lambda: s.tap("Cancelar"),
    )

    s = Session()
    s.say("la clave del wifi es larga")
    s.tap("Nota")
    cat.snap(s, "Nota guardada con su área.", lambda: s.tap("universidad"))

    s = Session()
    for area in areas.list_areas(s.conn):
        areas.archive_area(s.conn, area.id)
    s.say("comprar leche")
    cat.snap(s, "Sin áreas disponibles no se pregunta el área.", lambda: s.tap("Tarea"))

    s = Session()
    s.say("mañana 8am llevar tarea")
    s.tap("Recordatorio")
    cat.snap(
        s,
        "Recordatorio con fecha clara: edición del área y confirmación con Cambiar/Deshacer.",
        lambda: s.tap("universidad"),
    )
    cat.snap(
        s,
        "Deshacer: el recordatorio se cancela y la tarea vuelve a la bandeja.",
        lambda: s.tap("Deshacer"),
    )

    s = Session()
    s.say("mañana 8am llevar tarea")
    s.tap("Recordatorio")
    s.tap("universidad")
    cat.snap(s, "Cambiar: se deshace y se vuelve a preguntar la fecha.", lambda: s.tap("Cambiar"))
    cat.snap(s, "Se responde la fecha escribiéndola.", lambda: s.say("pasado mañana 10 am"))

    s = Session()
    s.say("mañana llevar tarea")
    s.tap("Recordatorio")
    cat.snap(
        s,
        "Fecha sin hora: la confirmación avisa de la hora por defecto.",
        lambda: s.tap("Sin área"),
    )

    s = Session()
    s.say("todos los lunes a las 7 pm regar plantas")
    s.tap("Recordatorio")
    cat.snap(
        s,
        "Repetición: vista previa con la próxima fecha, sin guardar todavía.",
        lambda: s.tap("Sin área"),
    )
    cat.snap(s, "Guardar la repetición: confirmación.", lambda: s.tap("Guardar"))

    s = Session()
    cat.snap(
        s,
        "Un texto que empieza por «recordar/recuérdame» salta la pregunta de tipo.",
        lambda: s.say("recuérdame llamar a mamá"),
    )
    cat.snap(
        s,
        "Sin fecha: pregunta ¿cuándo? con opciones rápidas y «Mejor como tarea».",
        lambda: s.tap("Sin área"),
    )
    cat.snap(s, "Se elige una opción rápida: confirmación.", lambda: s.tap("Mañana 9:00"))

    s = Session()
    s.say("llamar al dentista")
    s.tap("Recordatorio")
    s.tap("iglesia")
    cat.snap(
        s,
        "Mejor como tarea: queda como tarea con el área ya elegida, sin recordatorio.",
        lambda: s.tap("Mejor como tarea"),
    )

    s = Session()
    s.say("llamar al dentista")
    s.tap("Recordatorio")
    s.tap("Sin área")
    cat.snap(
        s,
        "En ¿cuándo?, «Escribir otra»/texto: si lo escrito no es una fecha, es una captura nueva y se avisa.",
        lambda: s.say("comprar leche"),
    )

    s = Session()
    s.say("comprar leche")
    old = s._last_choices(None)[0].id
    s.say("sacar copias")
    cat.snap(s, "Botón de una pregunta vieja: se ignora.", lambda: s.press(old))

    s = Session(START + timedelta(hours=2, minutes=25))  # 17:55
    s.say("llamar al dentista")
    s.tap("Recordatorio")
    s.tap("Sin área")
    hoy_button = next(c.id for c in s._last_choices(None) if c.label == "Hoy 18:00")
    s.clock.advance(minutes=6)
    cat.snap(
        s, "La opción «Hoy 18:00» se pulsó cuando ya había pasado.", lambda: s.press(hoy_button)
    )


def preguntas_del_parser(cat: Catalog) -> None:
    cat.section(
        "Preguntas del parser de fechas (recordatorios)",
        "Se llega con «Recordatorio» y un área; aquí se muestra solo la pregunta que sale.",
    )

    def ask(comment: str, text: str, start: datetime = START) -> None:
        s = Session(start)
        s.say(f"recordar {text}")
        cat.snap(s, comment, lambda: s.tap("Sin área"))

    ask("Hora o cita bíblica (time_or_verse).", "llamar a Juan 3:30")
    ask("Persona o día (name_or_day).", "llamar a Domingo")
    ask("Hora con punto (dotted_time).", "mañana 7.30 dentista")
    ask("Número pegado al día (number_after_day).", "mañana 7 dentista")
    ask("Fecha que no entiende (unsupported_date): opciones rápidas.", "pagar renta próximo mes")
    ask("Repetición que no sabe hacer (unrecognized_recurrence).", "cada mes pagar renta")
    ask("Medianoche dudosa (ambiguous_time).", "mañana a las 12 am cena")
    ask("Hora dudosa, dos lecturas (ambiguous_meridiem).", "mañana a las 9 llevar tarea")
    ask("Hora dudosa, un solo candidato futuro (ambiguous_meridiem).", "hoy a las 8 llevar tarea")
    ask("Hora que ya pasó, con alternativa (past).", "hoy a las 10 am llevar tarea")
    ask("Día igual al de hoy (same_weekday).", "llamar el sábado")
    ask(
        "Pasada la medianoche, «mañana» dudoso (today_or_tomorrow).",
        "mañana a las 8 am llevar tarea",
        datetime(2026, 10, 4, 6, 40, tzinfo=UTC),  # domingo 00:40 locales
    )
    ask("Cualquier otra duda (texto genérico).", "mañana por la mañana llevar tarea")


# --- Aviso de recordatorio ---------------------------------------------------------------------


def avisos(cat: Catalog) -> None:
    cat.section(
        "Aviso de recordatorio y sus botones",
        "Lo que sale cuando el motor envía un recordatorio (tipo de envío `reminder`).",
    )
    s = Session()
    reminders.create_reminder(
        s.conn,
        "llevar tarea",
        s.clock() + timedelta(minutes=1),
        s.clock,
        area_id=areas.find_area_by_name(s.conn, "universidad").id,
    )
    s.clock.advance(minutes=1)
    cat.snap(s, "Aviso a su hora, con el área entre corchetes.", s.tick)
    cat.snap(s, "Hecho.", lambda: s.tap("Hecho"))

    s = Session()
    reminders.create_reminder(s.conn, "llamar a mamá", s.clock() + timedelta(minutes=1), s.clock)
    s.clock.advance(minutes=1)
    s.tick()
    cat.snap(s, "+10 min: se reprograma para hoy.", lambda: s.tap("+10 min"))

    s = Session()
    reminders.create_reminder(s.conn, "llamar a mamá", s.clock() + timedelta(minutes=1), s.clock)
    s.clock.advance(minutes=1)
    s.tick()
    cat.snap(
        s,
        "Mañana 9:00: se reprograma para el día siguiente (día completo en la confirmación).",
        lambda: s.tap("Mañana 9:00"),
    )
    ids = [c.id for c in s._last_choices(None)]
    cat.snap(
        s, "Pulsar otra vez un botón de un aviso que ya no está activo.", lambda: s.press(ids[0])
    )
    cat.snap(s, "Botón de un recordatorio que no existe.", lambda: s.press("rem_done:9999"))

    s = Session()
    reminders.create_reminder(s.conn, "llamar a mamá", s.clock() + timedelta(minutes=1), s.clock)
    s.clock.advance(minutes=10)
    cat.snap(s, "Aviso que salió tarde (caída, silencio o canal caído): «(retrasado)».", s.tick)

    s = Session(
        datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
    )  # sábado 3 a las 02:00 locales... domingo madrugada
    s.clock.current = local("2026-10-04 03:00")
    reminders.create_reminder(
        s.conn, "revisar el horno", s.clock() + timedelta(minutes=1), s.clock, priority=2
    )
    s.clock.advance(minutes=1)
    cat.snap(
        s,
        "De madrugada (antes de las 5:00) el botón dice «Hoy 9:00» en lugar de «Mañana 9:00».",
        s.tick,
    )

    s = Session()
    tasks.create_task(
        s.conn,
        "entregar proyecto",
        s.clock,
        due_at_utc=local("2026-10-05 15:30"),
        area_id=areas.find_area_by_name(s.conn, "universidad").id,
    )
    s.clock.current = local("2026-10-04 15:31")
    cat.snap(s, "Aviso de preparación, un día antes de la fecha de una tarea.", s.tick)
    s.clock.current = local("2026-10-05 14:31")
    cat.snap(s, "Aviso de preparación, una hora antes.", s.tick)


# --- Comandos ----------------------------------------------------------------------------------


def seeded() -> Session:
    s = Session()
    uni = areas.find_area_by_name(s.conn, "universidad").id
    personal = areas.find_area_by_name(s.conn, "personal").id

    def add(title, due=None, area=None):
        task = tasks.create_task(s.conn, title, s.clock, area_id=area)
        if due:
            with s.conn:
                s.conn.execute(
                    "UPDATE tasks SET due_at_utc = ? WHERE id = ?",
                    (local(due).isoformat(timespec="seconds"), task.id),
                )

    add("entregar informe", "2026-10-03 17:00", uni)
    add("pagar luz", "2026-10-02 17:00")
    add("regar plantas", "2026-10-04 09:00", personal)
    add("comprar pan")
    reminders.create_reminder(s.conn, "llamar a mamá", local("2026-10-03 18:00"), s.clock)
    reminders.create_reminder(
        s.conn, "llevar tarea", local("2026-10-04 08:00"), s.clock, area_id=uni
    )
    reminders.create_reminder(
        s.conn,
        "ir a la iglesia",
        local("2026-10-04 10:00"),
        s.clock,
        area_id=areas.find_area_by_name(s.conn, "iglesia").id,
        rrule="FREQ=WEEKLY;BYDAY=SU",
    )
    return s


def hoy(cat: Catalog) -> None:
    cat.section("/hoy [área]")
    s = Session()
    cat.snap(s, "Sin nada para hoy.", lambda: s.say("/hoy"))
    s = seeded()
    cat.snap(
        s, "Con tareas vencidas, de hoy, recordatorios de hoy y la bandeja.", lambda: s.say("/hoy")
    )
    cat.snap(s, "Filtrado por área (sin la línea de bandeja).", lambda: s.say("/hoy universidad"))
    cat.snap(s, "Área que no existe.", lambda: s.say("/hoy inventada"))


def pendientes(cat: Catalog) -> None:
    cat.section("/pendientes [área]", "Un mensaje por tarea, cada uno con sus botones.")
    s = Session()
    cat.snap(s, "Sin tareas.", lambda: s.say("/pendientes"))
    s = seeded()
    cat.snap(s, "Lista: encabezado y una tarea por mensaje.", lambda: s.say("/pendientes"))
    cat.snap(s, "Hecha.", lambda: s.tap("Hecha", "regar plantas"))
    cat.snap(s, "Descartar.", lambda: s.tap("Descartar", "comprar pan"))
    cat.snap(
        s, "Pulsar otra vez sobre una tarea ya cerrada.", lambda: s.tap("Hecha", "regar plantas")
    )
    cat.snap(s, "Filtrado por área.", lambda: s.say("/pendientes universidad"))
    s = Session()
    for number in range(13):
        tasks.create_task(s.conn, f"tarea {number + 1}", s.clock)
    cat.snap(s, "Más de 10 tareas: se muestran 10 y se avisa.", lambda: s.say("/pendientes"))


def recordatorios(cat: Catalog) -> None:
    cat.section("/recordatorios")
    s = Session()
    cat.snap(s, "Sin recordatorios pendientes.", lambda: s.say("/recordatorios"))
    s = seeded()
    cat.snap(s, "Lista de pendientes, con área y repetición.", lambda: s.say("/recordatorios"))
    with s.conn:
        s.conn.execute(
            "UPDATE reminders SET stop_reason = 'permanent:bot_blocked' WHERE text = 'llamar a mamá'"
        )
        s.conn.execute(
            "UPDATE reminders SET stop_reason = 'permanent:algo_raro' WHERE text = 'llevar tarea'"
        )
    cat.snap(
        s, "Con detenidos: motivo conocido y motivo desconocido.", lambda: s.say("/recordatorios")
    )
    with s.conn:
        for code in (
            "permanent:chat_not_found",
            "permanent:message_too_long",
            "permanent:bad_request:cant_parse_entities",
            "permanent:bad_request:empty_text",
            "permanent:bad_request:button_data_invalid",
            "permanent:bad_request:other",
            "horizon:telegram_down",
            "legacy",
            "permanent:unexpected:KeyError",
        ):
            reminders.create_reminder(s.conn, code, local("2026-10-05 08:00"), s.clock)
            s.conn.execute("UPDATE reminders SET stop_reason = ? WHERE text = ?", (code, code))
    cat.snap(s, "Todos los motivos de detención que se explican.", lambda: s.say("/recordatorios"))


def recordar(cat: Catalog) -> None:
    cat.section("/recordar")
    s = Session()
    cat.snap(s, "Sin texto.", lambda: s.say("/recordar"))
    cat.snap(
        s,
        "Con texto: se guarda en la bandeja y pregunta el área.",
        lambda: s.say("/recordar mañana 8am llevar tarea"),
    )
    cat.snap(s, "Vista previa antes de guardar.", lambda: s.tap("universidad"))
    cat.snap(s, "Guardar: confirmación.", lambda: s.tap("Guardar"))
    s = Session()
    s.say("/recordar todos los lunes a las 7 pm regar plantas")
    cat.snap(s, "Con repetición: vista previa con la próxima fecha.", lambda: s.tap("Sin área"))
    s = Session()
    s.say("/recordar mañana a las 9 llevar tarea")
    s.tap("Sin área")
    cat.snap(
        s,
        "Con una duda del parser: se elige el candidato y luego se muestra la vista previa.",
        lambda: s.tap("9:00 pm"),
    )


def tarea(cat: Catalog) -> None:
    cat.section("/tarea")
    s = Session()
    cat.snap(s, "Sin texto.", lambda: s.say("/tarea"))
    cat.snap(s, "Con texto: pregunta solo el área.", lambda: s.say("/tarea comprar pan"))
    cat.snap(s, "Área elegida.", lambda: s.tap("personal"))
    s = Session()
    s.say("/tarea entregar informe el viernes")
    cat.snap(
        s,
        "Con una fecha clara en el texto: pregunta si es la fecha límite.",
        lambda: s.tap("universidad"),
    )
    cat.snap(s, "Sí: título sin la fecha, con fecha de vencimiento.", lambda: s.tap("Sí"))
    s = Session()
    s.say("/tarea entregar informe el viernes")
    s.tap("universidad")
    cat.snap(s, "No: queda con el texto completo y sin fecha.", lambda: s.tap("No"))


def nota(cat: Catalog) -> None:
    cat.section("/nota")
    s = Session()
    cat.snap(s, "Sin texto.", lambda: s.say("/nota"))
    cat.snap(s, "Con texto: pregunta solo el área.", lambda: s.say("/nota la clave del wifi"))
    cat.snap(s, "Área elegida.", lambda: s.tap("personal"))


def areas_y_nuevaarea(cat: Catalog) -> None:
    cat.section("/areas y /nuevaarea")
    s = Session()
    cat.snap(s, "Lista de áreas.", lambda: s.say("/areas"))
    s.say("/nuevaarea Salud")
    s.tap("Omitir")
    cat.snap(s, "Un área sin descripción se marca.", lambda: s.say("/areas"))
    s = Session()
    for area in areas.list_areas(s.conn):
        areas.archive_area(s.conn, area.id)
    cat.snap(s, "Sin áreas.", lambda: s.say("/areas"))

    s = Session()
    cat.snap(s, "/nuevaarea sin nombre.", lambda: s.say("/nuevaarea"))
    cat.snap(s, "Con nombre: pregunta la descripción.", lambda: s.say("/nuevaarea Salud"))
    cat.snap(s, "Se escribe la descripción.", lambda: s.say("Ejercicio y citas médicas"))
    s.say("/nuevaarea Deportes")
    cat.snap(s, "Omitir: el área queda sin descripción.", lambda: s.tap("Omitir"))
    s.say("/nuevaarea Viajes")
    cat.snap(s, "Cancelar.", lambda: s.tap("Cancelar"))
    cat.snap(
        s,
        "Nombre repetido (sin distinguir mayúsculas ni acentos).",
        lambda: s.say("/nuevaarea UNIVERSIDÁD"),
    )
    cat.snap(s, "Nombre demasiado largo.", lambda: s.say("/nuevaarea " + "x" * 41))


def ayuda(cat: Catalog) -> None:
    cat.section("/start y /ayuda")
    s = Session()
    cat.snap(s, "/start.", lambda: s.say("/start"))
    cat.snap(s, "/ayuda.", lambda: s.say("/ayuda"))


def errores(cat: Catalog) -> None:
    cat.section("Errores y avisos generales")
    s = Session()
    cat.snap(s, "Comando desconocido.", lambda: s.say("/inventado"))
    cat.snap(s, "Botón desconocido o mal formado.", lambda: s.press("zzz:1"))
    cat.snap(s, "Botón de la bandeja de un flujo que ya no existe.", lambda: s.press("in:1:k:t"))
    cat.snap(s, "Botón de tarea que no existe.", lambda: s.press("tk_done:9999"))
    s.say("llamar al dentista")
    s.tap("Recordatorio")
    s.tap("Sin área")
    s.tap("Mañana 9:00")
    first = s._last_choices(None)
    s.tap("Deshacer")
    cat.snap(
        s,
        "Deshacer/Cambiar cuando el recordatorio ya no está pendiente.",
        lambda: s.press(first[1].id),
    )
    s2 = Session()
    s2.say("/nuevaarea Salud")
    s2.say("/nuevaarea Deportes")
    cat.snap(
        s2,
        "Un comando a mitad de otra pregunta no la descarta; otro flujo nuevo sí, y avisa.",
        lambda: s2.say("/tarea sacar copias"),
    )


def render() -> str:
    """El catálogo completo como texto Markdown (lo usa también la prueba de instantánea)."""
    return "\n".join(build().lines).rstrip("\n") + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    catalog = build()
    text = "\n".join(catalog.lines).rstrip("\n") + "\n"
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    print(f"[{catalog.screens} pantallas guardadas en {OUTPUT}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
