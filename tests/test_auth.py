import pytest

from asistente.bot.auth import is_allowed


def test_usuario_autorizado():
    assert is_allowed("12345", 12345) is True


@pytest.mark.parametrize("user_ref", ["99999", "", "abc", " 12345", "012345", "12345.0", "-12345"])
def test_cualquier_otro_se_rechaza(user_ref: str):
    assert is_allowed(user_ref, 12345) is False
