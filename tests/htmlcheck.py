"""Validador ESTRICTO del subconjunto de HTML que enviamos a Telegram (<b>, <i>, <code>).

Telegram rechaza con `can't parse entities` un `<` o `>` sueltos, una etiqueta desconocida o sin
cerrar, o un `&` que no empieza una entidad. Aquí se comprueba lo mismo, para que una prueba falle
ANTES de que Telegram lo haga.
"""

from __future__ import annotations

import re

ALLOWED_TAGS = ("b", "i", "code")
_TAG = re.compile(r"</?(?:b|i|code)>")
_ENTITY = re.compile(r"&(?:lt|gt|amp|quot);")


def html_problems(text: str) -> list[str]:
    problems: list[str] = []
    stack: list[str] = []
    rest = []
    position = 0
    for match in _TAG.finditer(text):
        rest.append(text[position : match.start()])
        position = match.end()
        tag = match.group()
        name = tag.strip("</>")
        if tag.startswith("</"):
            if not stack or stack[-1] != name:
                problems.append(f"cierre inesperado {tag}")
            else:
                stack.pop()
        else:
            stack.append(name)
    rest.append(text[position:])
    if stack:
        problems.append(f"etiquetas sin cerrar: {stack}")
    outside = "".join(rest)
    if "<" in outside or ">" in outside:
        problems.append("< o > sueltos")
    if "&" in _ENTITY.sub("", outside):
        problems.append("& suelto")
    return problems


def assert_valid_telegram_html(text: str) -> None:
    problems = html_problems(text)
    assert not problems, (problems, text)
