"""Opciones como datos (`Choice`), sin nada específico de una plataforma.

El `id` de cada opción tiene la forma `accion:parte1:parte2`, p. ej. `done:42`.
Telegram limita ese texto a 64 bytes, así que se valida aquí para fallar pronto.
"""

from __future__ import annotations

MAX_CHOICE_ID_BYTES = 64
SEPARATOR = ":"


def encode_choice_id(action: str, *parts: object) -> str:
    """Arma un id de opción: `encode_choice_id("done", 42)` -> `"done:42"`."""
    choice_id = SEPARATOR.join([action, *(str(part) for part in parts)])
    if len(choice_id.encode("utf-8")) > MAX_CHOICE_ID_BYTES:
        raise ValueError(f"El id de opción supera {MAX_CHOICE_ID_BYTES} bytes")
    return choice_id


def decode_choice_id(choice_id: str) -> tuple[str, list[str]]:
    """Inverso de `encode_choice_id`: `"done:42"` -> `("done", ["42"])`."""
    action, *parts = choice_id.split(SEPARATOR)
    return action, parts
