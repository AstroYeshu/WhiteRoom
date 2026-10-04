"""El README no debe quedarse atrás: los archivos y comandos que menciona existen."""

import re
from pathlib import Path

from asistente.bot import commands

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_los_archivos_y_scripts_que_menciona_existen():
    mentioned = set(re.findall(r"(?:scripts|deploy)/[\w.]+", README)) | {".env.example"}
    assert {"scripts/check_env.py", "scripts/backup_db.py", "deploy/asistente.service"} <= mentioned
    for path in mentioned:
        assert (ROOT / path).exists(), path


def test_menciona_cada_comando_del_bot():
    for name in (*commands.COMMANDS, "ayuda"):
        assert f"/{name}" in README, name


def test_tiene_las_secciones_pedidas():
    for heading in (
        "## Instalación en la laptop",
        "## Desarrollo y producción: dos bots, dos bases",
        "## Despliegue en Raspberry Pi",
        "## Cómo actualizar",
        "## Cómo restaurar un respaldo",
        "## Checklist de aceptación en la Pi",
    ):
        assert heading in README, heading
    for needle in ("timedatectl", "journalctl -u asistente -f", "check_env", "git pull",
                   "pip install -r requirements.txt", "reboot"):  # fmt: skip
        assert needle in README, needle


def test_el_ejemplo_de_unidad_usa_los_mismos_marcadores_que_el_archivo():
    service = (ROOT / "deploy" / "asistente.service").read_text(encoding="utf-8")
    for marker in ("<USUARIO>", "<RUTA_PROYECTO>"):
        assert marker in README and marker in service


def test_las_variables_que_pide_el_readme_estan_en_el_ejemplo():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for variable in (
        "TELEGRAM_BOT_TOKEN",
        "ALLOWED_USER_ID",
        "TZ_NAME",
        "CURRENCY_CODE",
        "BOT_ENV",
    ):
        assert f"{variable}=" in example, variable
        assert variable in README, variable
