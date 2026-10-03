"""Filtro de acceso: solo se atiende al dueño (`ALLOWED_USER_ID`)."""

from __future__ import annotations


def is_allowed(user_ref: str, allowed_user_id: int) -> bool:
    """True solo si `user_ref` es exactamente el ID autorizado, carácter por carácter.

    Sin normalizar nada: "007", " 7" o "7.0" no se cuelan por formato.
    """
    return user_ref == str(allowed_user_id)
