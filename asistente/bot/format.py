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


STALE_CHOICE = aviso("Esa opción ya no está disponible.")
UNKNOWN_COMMAND = aviso("No conozco ese comando. Escribe /ayuda para ver los disponibles.")
REMINDER_NOT_ACTIVE = aviso("Este recordatorio ya no está activo.")
