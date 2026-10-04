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
from collections.abc import Iterable
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
    detail = "Recordatorio" + (f"{SEP}{esc(area)}" if area else "")
    if delayed:
        detail += f" {italic('(retrasado)')}"
    return paragraphs(bold(text), Html(detail))


def state_line(state: str, text: str, detail: str | None = None) -> Html:
    """Confirmación de una acción en una línea: la palabra de estado en negrita y luego el texto."""
    parts: list[str] = [bold(state), text]
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
