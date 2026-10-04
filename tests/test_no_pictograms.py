"""Los mensajes al usuario no llevan emojis ni pictogramas (CLAUDE.md, "Convenciones").

La prueba recorre con `ast` todas las constantes de texto de `asistente/` y `scripts/` (incluidas
las partes literales de las f-strings y los docstrings) y falla si encuentra un pictograma:
emoticonos, símbolos, dingbats, flechas, selectores de variación, ZWJ o marcos de teclado.
No prohíbe las letras con tilde, la eñe, ni la puntuación normal del español.
Las expresiones con caracteres especiales se escriben con escapes \\u, nunca como literales.
"""

import ast
import pathlib
import unicodedata

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("asistente", "scripts")

# Símbolos (categorías So, Sm, Sk) que SÍ son texto normal: el grado de los ordinales "1°".
ALLOWED_SYMBOLS = {"\u00b0"}
SYMBOL_CATEGORIES = {"So", "Sm", "Sk"}
INVISIBLE_PICTOGRAM_PARTS = {0x200D, 0x20E3}  # unión de emojis y marco de teclado
VARIATION_SELECTORS = range(0xFE00, 0xFE10)


def is_pictogram(char: str) -> bool:
    code = ord(char)
    if code < 128 or char in ALLOWED_SYMBOLS:
        return False
    if unicodedata.category(char) in SYMBOL_CATEGORIES:
        return True
    return code in VARIATION_SELECTORS or code in INVISIBLE_PICTOGRAM_PARTS


def find_pictograms(text: str) -> list[str]:
    return [char for char in text if is_pictogram(char)]


def string_constants(source: str) -> list[str]:
    """Todas las constantes de texto del código (docstrings y partes literales de f-strings)."""
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def offenders() -> list[str]:
    found: list[str] = []
    for directory in SCANNED_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            for constant in string_constants(path.read_text(encoding="utf-8")):
                bad = find_pictograms(constant)
                if bad:
                    codes = " ".join(f"U+{ord(char):04X}" for char in bad)
                    found.append(f"{path.relative_to(ROOT).as_posix()}: {codes}")
    return found


def test_ningun_texto_del_codigo_lleva_pictogramas():
    assert offenders() == []


# --- El detector funciona -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "\u23f0 Recordatorio",  # alarma
        "\u2705 Hecho",  # marca verde
        "hola \U0001f4dd",  # fuera del plano básico
        "\u2764\ufe0f",  # corazón con selector de variación
        "1\ufe0f\u20e3 una vez",  # marco de teclado
        "\u21a9 Deshacer",  # flecha
        "\u2192 tarde",  # flecha simple
        "\u2208 conjunto",  # símbolo matemático
        "\U0001f469\u200d\U0001f4bb",  # emoji compuesto con unión
        "\u00a9 2026",  # símbolo de copyright
    ],
)
def test_el_detector_ve_los_pictogramas(text):
    assert find_pictograms(text) != []


def test_el_detector_ve_un_emoji_dentro_de_una_f_string_y_de_un_docstring():
    source = 'def f(a):\n    """Docstring \\u2705."""\n    return f"hola {a} \\u23f0"\n'
    found = [bad for constant in string_constants(source) for bad in find_pictograms(constant)]
    assert found == ["\u2705", "\u23f0"]


def test_el_detector_no_prohibe_el_espanol_normal():
    text = (
        "\u00e1 \u00e9 \u00ed \u00f3 \u00fa \u00f1 \u00fc "
        "\u00c1 \u00c9 \u00cd \u00d3 \u00da \u00d1 "
        "\u00bf \u00a1 \u00ab \u00bb \u2026 \u2014 \u2013 \u00b7 "
        "\u00ba \u00aa \u00b0 + - > < = % $ "
        "(retrasado) Hoy 9:00 am"
    )
    assert find_pictograms(text) == []
