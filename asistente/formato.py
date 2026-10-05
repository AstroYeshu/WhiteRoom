"""Presentación de los mensajes: funciones PURAS que generan textos y la distribución de botones.

Marcado mínimo, un subconjunto de HTML que entiende Telegram: `<b>`, `<i>` y `<code>`. El texto del
usuario SIEMPRE se escapa (`esc`): los constructores (`bold`, `italic`, `code`, `block`...) escapan
todo lo que no sea ya `Html`, así que olvidarse de escapar no es posible por esa vía.

`Html` es un `str` marcado como "ya es HTML seguro". Los canales aplican `to_html` al enviar: un
`str` normal se escapa (se muestra tal cual, sin formato) y un `Html` pasa sin tocarse. La consola
usa `plain`, que quita las etiquetas. Los emojis y pictogramas están prohibidos; el punto medio (·)
y la raya (—) son puntuación normal.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from asistente.parsing.dates import format_when
from asistente.timeutil import Clock, to_local

SEP = " · "  # punto medio entre detalles: "Recordatorio · universidad"
MAX_LABEL = 22  # caracteres máximos de la etiqueta de un botón

WEEKDAYS_SHORT = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MONTHS_SHORT = (
    "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic",
)  # fmt: skip

_OWN_TAGS = re.compile(r"</?(?:b|i|code)>")


class Html(str):
    """Texto que YA es HTML seguro (solo `<b>`, `<i>`, `<code>` y entidades `&lt; &gt; &amp;`)."""

    __slots__ = ()


def esc(text: str) -> str:
    """Escapa `&`, `<` y `>` (lo único que Telegram exige). Las comillas no necesitan escape."""
    return html.escape(text, quote=False)


def _safe(value: str) -> Html:
    return value if isinstance(value, Html) else Html(esc(value))


def bold(value: str) -> Html:
    return Html(f"<b>{_safe(value)}</b>")


def italic(value: str) -> Html:
    return Html(f"<i>{_safe(value)}</i>")


def code(value: str) -> Html:
    return Html(f"<code>{_safe(value)}</code>")


def join(parts: Iterable[str], separator: str) -> Html:
    return Html(separator.join(_safe(part) for part in parts))


def block(*lines: str) -> Html:
    """Líneas seguidas, sin línea en blanco."""
    return join(lines, "\n")


def paragraphs(*blocks: str) -> Html:
    """Bloques separados por una línea en blanco."""
    return join(blocks, "\n\n")


def to_html(text: str) -> str:
    """Lo que se envía a Telegram con `parse_mode=HTML`: un `str` plano se escapa."""
    return _safe(text)


def plain(text: str) -> str:
    """El texto sin formato (consola y reintento en texto plano). Un `str` plano no se toca."""
    if not isinstance(text, Html):
        return str(text)
    return html.unescape(_OWN_TAGS.sub("", text))


_OPENING_MARKS = "¿¡"  # signos de apertura: la mayúscula va en la primera letra tras ellos


def cap_first(text: str) -> str:
    """Pone en mayúscula la primera letra SOLO si es una letra minúscula; el resto no se toca.

    Es para MOSTRAR (nunca se guarda así). Salta los "¿" y "¡" iniciales ("¿qué?" -> "¿Qué?");
    no cambia números ni símbolos ("123 a" queda igual). Una primera palabra con mayúsculas
    propias ("iOS", "iPhone") se respeta: ya está escrita como su dueño la quiere.
    """
    start = len(text) - len(text.lstrip(_OPENING_MARKS))
    if start == len(text) or not text[start].islower():
        return text
    first_word = text[start:].split(maxsplit=1)[0]
    if any(char.isupper() for char in first_word[1:]):
        return text
    upper = text[start].upper()
    if len(upper) != 1:  # "ß".upper() es "SS": no cambia la longitud del texto
        return text
    return text[:start] + upper + text[start + 1 :]


def label(text: str) -> str:
    """Etiqueta de botón: como máximo `MAX_LABEL` caracteres (corta con puntos suspensivos)."""
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_LABEL else flat[: MAX_LABEL - 1].rstrip() + "…"


# --- Fechas ------------------------------------------------------------------------------------


def _hour(local: datetime) -> str:
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


def hora(moment_utc: datetime, tz_name: str) -> str:
    """La hora local con am/pm: "9:00 am"."""
    return _hour(to_local(moment_utc, tz_name))


def etiqueta_hora(day: str, moment_utc: datetime, tz_name: str) -> str:
    """Etiqueta de botón con día y hora, siempre am/pm como el resto: "Mañana 9:00 am"."""
    return f"{day} {_hour(to_local(moment_utc, tz_name))}"


def fecha_corta(moment_utc: datetime, tz_name: str, now: Clock) -> str:
    """Para botones y listas: "hoy, 6:00 pm", "mañana, 8:00 am", "sáb 3 oct, 6:00 pm".

    De otro año va con el año y sin día de la semana ("14 mar 2027, 8:00 am"), para caber
    en un botón.
    """
    local = to_local(moment_utc, tz_name)
    today = to_local(now(), tz_name).date()
    days = (local.date() - today).days
    if days == 0:
        return f"hoy, {_hour(local)}"
    if days == 1:
        return f"mañana, {_hour(local)}"
    month = MONTHS_SHORT[local.month - 1]
    if local.year != today.year:
        return f"{local.day} {month} {local.year}, {_hour(local)}"
    return f"{WEEKDAYS_SHORT[local.weekday()]} {local.day} {month}, {_hour(local)}"


def fecha_vencida(moment_utc: datetime, tz_name: str, now: Clock) -> str:
    """Solo el día de lo que ya venció, para «venció ...»: "hoy", "vie 2 oct", "14 mar 2025"."""
    local = to_local(moment_utc, tz_name)
    today = to_local(now(), tz_name).date()
    if local.date() == today:
        return "hoy"
    month = MONTHS_SHORT[local.month - 1]
    if local.year != today.year:
        return f"{local.day} {month} {local.year}"
    return f"{WEEKDAYS_SHORT[local.weekday()]} {local.day} {month}"


def fecha_larga(moment_utc: datetime, tz_name: str, now: Clock) -> str:
    """Solo para confirmaciones: "sábado 3 de octubre, 6:00 pm"."""
    return format_when(moment_utc, tz_name, now)


# --- Botones -----------------------------------------------------------------------------------


def rows_layout(count: int, per_row: int = 2, last_alone: bool = False) -> tuple[int, ...]:
    """Cuántos botones lleva cada fila: de `per_row` en `per_row`; con `last_alone` el último
    (Cancelar) va solo, al final."""
    if count <= 0:
        return ()
    main = count - 1 if last_alone else count
    layout = [per_row] * (main // per_row)
    if main % per_row:
        layout.append(main % per_row)
    if last_alone:
        layout.append(1)
    return tuple(layout)


REMINDER_LAYOUT = (2, 2)  # Hecho · +10 min / +1 h · Mañana 9:00


# --- Piezas de mensaje -------------------------------------------------------------------------


def reminder_notice(text: str, area: str | None, delayed: bool) -> Html:
    """Contenido en negrita y, aparte, "Recordatorio · área" ("(retrasado)" en cursiva)."""
    detail = "Recordatorio" + (f"{SEP}{esc(cap_first(area))}" if area else "")
    if delayed:
        detail += f" {italic('(retrasado)')}"
    return paragraphs(bold(cap_first(text)), Html(detail))


def state_line(state: str, text: str, detail: str | None = None) -> Html:
    """Confirmación de una acción en una línea: la palabra de estado en negrita y luego el texto."""
    parts: list[str] = [bold(state), cap_first(text)]
    if detail:
        parts.append(detail)
    return join(parts, SEP)


def aviso(text: str) -> Html:
    """Errores y avisos generales: un solo formato."""
    return join([bold("Aviso"), text], SEP)


TOAST_STALE = "Esa opción ya no aplica"  # aviso breve (emergente), no un mensaje
STALE_CHOICE = aviso("Esa opción ya no está disponible.")
UNKNOWN_COMMAND = aviso("No conozco ese comando. Escribe /ayuda para ver los disponibles.")
REMINDER_NOT_ACTIVE = aviso("Este recordatorio ya no está activo.")


# --- Tarjetas: el mensaje único que evoluciona -----------------------------------------------


def detail(label_text: str, value: str) -> Html:
    """Una línea con etiqueta: "Área: universidad"."""
    return Html(f"{esc(label_text)}: {_safe(value)}")


def card(
    title: str,
    content: str | None = None,
    details: Iterable[str] = (),
    note: str | None = None,
) -> Html:
    """Una tarjeta: título en negrita; el contenido del usuario en su párrafo; los detalles con
    etiqueta juntos; una nota al final. Los bloques van separados por una línea en blanco."""
    blocks: list[str] = [bold(title)]
    if content:
        blocks.append(content)
    lines = list(details)
    if lines:
        blocks.append(block(*lines))
    if note:
        blocks.append(note)
    return paragraphs(*blocks)


def tail_layout(count: int, tail: int = 2) -> tuple[int, ...]:
    """Filas de 2; los últimos `tail` botones (Cancelar y, si hay, el que lo acompaña) van juntos
    en la fila final. Con `tail=2`: acción principal primero y [Otra fecha] [Cancelar] abajo."""
    if count <= 0:
        return ()
    tail = min(tail, count)
    return (*rows_layout(count - tail), tail)


# Títulos de las preguntas y de los estados finales (los textos de la conversación viven aquí).
Q_KIND = "¿Qué es?"
Q_AREA = "¿En qué área va?"
Q_WHEN = "¿Cuándo?"
Q_SAVE_REMINDER = "¿Guardo este recordatorio?"
Q_SAVE_SERIES = "¿Guardo esta repetición?"
Q_DEADLINE = "¿Es la fecha límite?"
DONE_TASK = "Tarea guardada"
DONE_NOTE = "Nota guardada"
DONE_REMINDER = "Recordatorio guardado"
DONE_AREA = "Área guardada"
CANCELLED = "Cancelado"
ABANDONED = "Sin terminar"
UNDONE = "Deshecho"
NOTE_IN_INBOX = "Sigue en tu bandeja como tarea."
NOTE_NO_AREA = "No se creó el área."
NOTE_NO_DESCRIPTION = "Sin descripción."
NOTE_AREA_DESCRIPTION = "Escribe una descripción corta u omítela."
HINT_WHEN = 'Pulsa una opción o escribe cuándo, p. ej. "en 2 horas" o "el viernes a las 5".'
HINT_WRITE_WHEN = "Escribe la fecha y la hora, por ejemplo «mañana 8 pm»."
HINT_PAST = "Esa hora ya pasó."
NOT_UNDOABLE = aviso("Ya no se puede deshacer ni cambiar: ese recordatorio ya no está pendiente.")

# Etiquetas de botón (como máximo MAX_LABEL caracteres).
BTN_CANCEL = "Cancelar"
BTN_OTHER_DATE = "Otra fecha"
BTN_SAVE = "Guardar"
BTN_CHANGE = "Cambiar"
BTN_UNDO = "Deshacer"
BTN_YES = "Sí"
BTN_NO = "No"
BTN_AS_TASK = "Mejor como tarea"
BTN_NO_AREA = "Sin área"
BTN_SKIP = "Omitir"

# Preguntas del parser de fechas (docs/PLAN_FASE1.md). Con candidatos, cada uno es un botón.
PARSER_QUESTIONS = {
    "time_or_verse": "¿Eso es una hora o una cita bíblica?",
    "name_or_day": "¿«Domingo» es una persona o el día de la semana?",
    "dotted_time": "¿Es una hora? Escríbela con dos puntos (por ejemplo 7:30).",
    "number_after_day": "¿Ese número es la hora o forma parte del texto? Escribe la hora completa.",
    "unsupported_date": "No entiendo esa fecha. ¿Qué día quieres?",
    "unrecognized_recurrence": (
        "Esa repetición no está entre las que sé hacer (todos los días, cada lunes, "
        "de lunes a viernes)."
    ),
    "ambiguous_time": "¿Medianoche de qué día?",
    "today_or_tomorrow": "Ya pasó la medianoche: ¿«mañana» es hoy o mañana?",
    "same_weekday": "Hoy es ese día: ¿hoy o en 7 días?",
}
PARSER_QUESTION_GENERIC = "No pude entender la fecha o la hora; escríbela de otra forma."


# --- Vistas: listas, secciones y pantallas -------------------------------------------------------


def clip(text: str, limit: int = 60) -> str:
    """El texto en una línea y como máximo `limit` caracteres (corta con puntos suspensivos)."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def bullet(*parts: str | None) -> Html:
    """Una viñeta con partes separadas por punto medio: "- título · área · hoy, 5:00 pm"."""
    kept = [part for part in parts if part]
    return Html("- " + SEP.join(_safe(part) for part in kept))


def numbered(items: Iterable[str]) -> Html:
    """Lista numerada desde 1: "1. a", "2. b"."""
    return block(*[Html(f"{number}. {_safe(item)}") for number, item in enumerate(items, start=1)])


def section(title: str, items: Sequence[str], limit: int = 15) -> Html:
    """Una sección: el título en negrita y sus líneas (como máximo `limit`; luego "y N más")."""
    lines: list[str] = [bold(title), *items[:limit]]
    if len(items) > limit:
        lines.append(f"y {len(items) - limit} más")
    return block(*lines)


def screen(title: str, *blocks: str | None) -> Html:
    """Una pantalla: título en negrita y bloques separados por una línea en blanco."""
    return paragraphs(bold(title), *[part for part in blocks if part])


@dataclass(frozen=True)
class PendingRow:
    """Una tarea de la lista de /pendientes."""

    title: str
    area: str | None = None
    when: str | None = None  # ya con `fecha_corta`


NOTHING_PENDING = "No tienes tareas pendientes. Todo al día."
TASK_PROMPT = "¿Qué hago con esta tarea?"
EMPTY_TODAY = "Nada para hoy: no hay tareas que venzan ni recordatorios."
NO_REMINDERS = "No tienes recordatorios pendientes."
NO_AREAS = "No hay áreas. Crea una con /nuevaarea nombre."
BTN_DONE = "Hecha"
BTN_DROP = "Descartar"
BTN_BACK = "Volver"
TASK_LIST_LIMIT = 15  # tareas por lista (/pendientes y la sección Tareas de /hoy)
LIST_LIMIT = 20  # líneas por sección de /recordatorios
TODAY_LIMIT = 15  # líneas por sección de /hoy


# --- Listas de tareas agrupadas por área (pura y reutilizable) -----------------------------------


@dataclass(frozen=True)
class AreaRef:
    """Un área tal como la necesita la agrupación: su id y su nombre."""

    id: int
    name: str


@dataclass(frozen=True)
class TaskItem:
    """Una tarea abierta para una lista. `when` ya viene en texto (`fecha_corta`)."""

    id: int
    title: str
    area_id: int | None
    due: datetime | None
    created: datetime
    when: str | None = None


@dataclass(frozen=True)
class TaskGroup:
    """Las tareas mostradas de un área; `area` es None para «Sin área»."""

    area: str | None
    items: tuple[TaskItem, ...]


@dataclass(frozen=True)
class TaskGroups:
    """El resultado de `group_tasks`: los grupos con algo que mostrar y cuántas tareas había."""

    groups: tuple[TaskGroup, ...]
    total: int

    @property
    def shown(self) -> tuple[TaskItem, ...]:
        """Las tareas mostradas en el orden de la numeración (1, 2, 3...)."""
        return tuple(one for group in self.groups for one in group.items)

    @property
    def hidden(self) -> int:
        return self.total - len(self.shown)


def _task_order(one: TaskItem) -> tuple:
    """Dentro de un área: primero las que tienen fecha (las vencidas, al ser más antiguas, abren la
    lista), por fecha; luego las que no tienen, por creación. El id desempata."""
    if one.due is None:
        return (1, one.created, one.id)
    return (0, one.due, one.created, one.id)


def group_tasks(
    items: Iterable[TaskItem], areas_in_order: Sequence[AreaRef], limit: int = TASK_LIST_LIMIT
) -> TaskGroups:
    """Agrupa tareas por área en un orden estable y corta en `limit`.

    Las áreas salen en el orden de `areas_in_order` (el mismo de /areas, con las archivadas al
    final); solo aparecen las que tienen tareas. Las tareas sin área (o con un área que no está en
    `areas_in_order`) van al final, bajo `area=None`. Lo que se corta por el límite es siempre el
    final de ese orden, y un área que se queda sin tareas mostradas pierde su grupo.
    """
    known = {area.id for area in areas_in_order}
    ordered = sorted(items, key=_task_order)
    groups: list[TaskGroup] = []
    remaining = limit
    sections = [
        (area.name, [one for one in ordered if one.area_id == area.id]) for area in areas_in_order
    ]
    sections.append((None, [one for one in ordered if one.area_id not in known]))
    total = 0
    for name, members in sections:
        total += len(members)
        kept = members[: max(remaining, 0)]
        remaining -= len(kept)
        if kept:
            groups.append(TaskGroup(name, tuple(kept)))
    return TaskGroups(tuple(groups), total)


NO_AREA_HEADER = "Sin área"


def task_list_block(groups: TaskGroups, headers: bool = True, numbered: bool = True) -> Html:
    """Las tareas en lista numerada con numeración continua (o con viñetas "-" si `numbered` es
    False). Con `headers`, cada área lleva su encabezado en negrita (y un renglón en blanco entre
    áreas); sin ellos, una sola lista."""
    number = 0
    blocks: list[str] = []
    for group in groups.groups:
        lines: list[str] = []
        if headers:
            lines.append(bold(cap_first(group.area) if group.area else NO_AREA_HEADER))
        for one in group.items:
            number += 1
            parts = [part for part in (cap_first(clip(one.title)), one.when) if part]
            mark = f"{number}. " if numbered else "- "
            lines.append(Html(mark + join(parts, SEP)))
        blocks.append(block(*lines))
    return paragraphs(*blocks) if headers else block(*blocks)


def task_list_footer(groups: TaskGroups, command: str, filtered: bool = False) -> str | None:
    """Si el límite dejó tareas fuera: «y N más: filtra por área (/comando nombre)»; con filtro de
    área ya activo, solo «y N más»."""
    if groups.hidden <= 0:
        return None
    if filtered:
        return f"y {groups.hidden} más"
    return f"y {groups.hidden} más: filtra por área ({command} nombre)"


def task_section(title: str, groups: TaskGroups, headers: bool, command: str) -> Html:
    """La sección de tareas de /hoy: su título en negrita y la lista agrupada, con viñetas (sin
    botones no hay nada que numerar). Sin encabezados es que hay filtro de área."""
    lines: list[str] = [bold(title), task_list_block(groups, headers, numbered=False)]
    footer = task_list_footer(groups, command, filtered=not headers)
    if footer:
        lines += ["", footer]
    return block(*lines)


def pending_list(groups: TaskGroups, area: str | None, note: str | None = None) -> Html:
    """/pendientes: título con el total y la lista agrupada. Con `area` (filtro) no hay
    encabezados; si el límite dejó tareas fuera, cuántas más hay."""
    title = "Pendientes" + (f"{SEP}{cap_first(area)}" if area else "") + f" ({groups.total})"
    if groups.total == 0:
        return screen(title, NOTHING_PENDING, note)
    body = task_list_block(groups, headers=area is None)
    footer = task_list_footer(groups, "/pendientes", filtered=area is not None)
    return screen(title, body, footer, note)


def pending_detail(row: PendingRow) -> Html:
    """Una tarea abierta desde la lista: su título y sus datos con etiqueta."""
    details = []
    if row.area:
        details.append(detail("Área", cap_first(row.area)))
    if row.when:
        details.append(detail("Vence", row.when))
    return card(cap_first(row.title), None, details, note=TASK_PROMPT)


def _help_group(title: str, *lines: str) -> Html:
    return block(bold(title), *lines)


HELP = screen(
    "Ayuda",
    _help_group(
        "Anotar",
        "Escribe cualquier mensaje: lo guardo en tu bandeja y te pregunto qué es.",
        f"/tarea texto{SEP}guardar una tarea",
        f"/nota texto{SEP}guardar una nota",
        f"/recordar texto{SEP}crear un recordatorio con su fecha",
    ),
    _help_group(
        "Consultar",
        f"/hoy [área]{SEP}lo que vence hoy",
        f"/pendientes [área]{SEP}tus tareas abiertas",
        f"/recordatorios{SEP}avisos pendientes y detenidos",
    ),
    _help_group(
        "Áreas",
        f"/areas{SEP}ver las áreas",
        f"/nuevaarea nombre{SEP}crear un área",
    ),
    _help_group(
        "Otros",
        f"/estado{SEP}estado del bot",
        f"/start{SEP}saludo",
        f"/ayuda{SEP}esta lista",
    ),
)
START = card(
    "Hola, soy tu asistente personal",
    note="Escribe lo que quieras anotar y te pregunto qué es. /ayuda muestra los comandos.",
)


# --- /estado -----------------------------------------------------------------------------------


def duration_text(seconds: float) -> str:
    """Una duración corta: "45 s", "5 min", "2 h 5 min", "1 d 3 h". Lo negativo cuenta como 0."""
    total = max(int(seconds), 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} d" + (f" {hours} h" if hours else "")
    if hours:
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def size_text(size_bytes: int) -> str:
    """Un tamaño de archivo: "512 B", "1.5 KB", "2.5 MB"."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / 1024**2:.1f} MB"


STATUS_UNAVAILABLE = aviso("El estado del bot no está disponible aquí.")


def counted(number: int, singular: str, plural: str) -> str:
    return f"{number} {singular if number == 1 else plural}"


def dia_largo(moment_utc: datetime, tz_name: str, now: Clock) -> str:
    """El día sin la hora: "sábado 3 de octubre"."""
    return fecha_larga(moment_utc, tz_name, now).rpartition(", ")[0]
