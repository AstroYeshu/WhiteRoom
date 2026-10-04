"""Los archivos de despliegue: la unidad systemd, los finales de línea y el .env.example."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "deploy" / "asistente.service"


def service_lines() -> list[str]:
    return [
        line.strip()
        for line in SERVICE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_la_unidad_tiene_lo_que_pide_el_spec():
    lines = service_lines()
    assert "After=network-online.target" in lines
    assert "Wants=network-online.target" in lines
    assert "Restart=always" in lines
    assert "RestartSec=5" in lines
    assert "WantedBy=multi-user.target" in lines
    assert any(line.startswith("User=") for line in lines)
    assert any(line.startswith("WorkingDirectory=") for line in lines)
    assert any(line.startswith("EnvironmentFile=") and line.endswith("/.env") for line in lines)


def test_la_unidad_arranca_el_modulo_con_el_python_del_venv():
    [exec_start] = [line for line in service_lines() if line.startswith("ExecStart=")]
    assert exec_start.endswith("/venv/bin/python -m asistente.main")


def test_los_marcadores_de_la_unidad_son_claros_y_no_hay_rutas_reales():
    text = SERVICE.read_text(encoding="utf-8")
    assert set(re.findall(r"<[A-Z_]+>", text)) == {"<USUARIO>", "<RUTA_PROYECTO>"}
    assert "/home/" not in "\n".join(service_lines())


def test_gitattributes_fuerza_lf_en_sh_service_y_sql():
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for pattern in ("*.sh", "*.service", "*.sql"):
        assert f"{pattern} text eol=lf" in lines


def test_los_archivos_con_eol_lf_no_tienen_crlf_en_el_repositorio():
    files = [SERVICE, *(ROOT / "asistente" / "migrations").glob("*.sql")]
    files += (ROOT / "scripts").glob("*.sh")
    for path in files:
        assert b"\r\n" not in path.read_bytes(), path.name


def test_env_example_no_tiene_comentarios_al_final_de_linea():
    """systemd (EnvironmentFile) los tomaría como parte del valor."""
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            assert "#" not in line, line
