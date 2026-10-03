from pathlib import Path

import pytest

from asistente.config import DRY_RUN_USER_ID, ConfigError, load_settings

FULL_ENV = {
    "TELEGRAM_BOT_TOKEN": "token-falso",
    "ALLOWED_USER_ID": "12345",
    "TZ_NAME": "America/Mexico_City",
    "CURRENCY_CODE": "mxn",
}


def test_dry_run_no_exige_secretos():
    settings = load_settings({}, dry_run=True)
    assert settings.dry_run is True
    assert settings.allowed_user_id == DRY_RUN_USER_ID
    assert settings.telegram_bot_token == ""


def test_dry_run_por_variable_de_entorno():
    assert load_settings({"DRY_RUN": "1"}).dry_run is True


def test_modo_real_lista_lo_que_falta_sin_valores():
    with pytest.raises(ConfigError) as error:
        load_settings({"TELEGRAM_BOT_TOKEN": "secreto"})
    assert "ALLOWED_USER_ID" in str(error.value)
    assert "secreto" not in str(error.value)


def test_valor_vacio_cuenta_como_ausente():
    with pytest.raises(ConfigError):
        load_settings({**FULL_ENV, "TELEGRAM_BOT_TOKEN": "  "})


def test_configuracion_completa_y_valores_por_defecto():
    settings = load_settings(FULL_ENV)
    assert settings.allowed_user_id == 12345
    assert settings.currency_code == "MXN"
    assert settings.db_path == Path("data/asistente.db")
    assert settings.classifier == "rules+jev"
    assert settings.log_level == "INFO"


def test_presupuesto_se_guarda_en_centavos_enteros():
    assert load_settings(FULL_ENV).monthly_api_budget_cents == 800
    env = {**FULL_ENV, "MONTHLY_API_BUDGET_USD": "7.50"}
    assert load_settings(env).monthly_api_budget_cents == 750


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ALLOWED_USER_ID", "abc"),
        ("TZ_NAME", "Marte/Olympus"),
        ("CLASSIFIER", "magia"),
        ("LOG_LEVEL", "CHISMOSO"),
        ("MONTHLY_API_BUDGET_USD", "mucho"),
        ("MONTHLY_API_BUDGET_USD", "1.234"),
    ],
)
def test_valores_invalidos(name: str, value: str):
    with pytest.raises(ConfigError):
        load_settings({**FULL_ENV, name: value})


def test_repr_no_filtra_secretos():
    assert "token-falso" not in repr(load_settings(FULL_ENV))
