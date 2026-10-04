"""`scripts/check_env.py`: verificación del entorno antes de arrancar el bot.

Todo con entornos y archivos temporales inyectados: nunca el `.env` real ni la base real.
"""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_env.py"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
SECRET = "123456:SECRETO-DEL-TOKEN"


def load_script():
    spec = importlib.util.spec_from_file_location("check_env", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # los dataclass lo necesitan
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return load_script()


@pytest.fixture
def env(tmp_path) -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": SECRET,
        "ALLOWED_USER_ID": "42",
        "TZ_NAME": "America/Mexico_City",
        "CURRENCY_CODE": "MXN",
        "DB_PATH": str(tmp_path / "data" / "asistente.db"),
    }


def by_name(results) -> dict[str, tuple[str, str]]:
    return {r.name: (r.status, r.detail) for r in results}


def status_of(script, name: str, env, **kwargs) -> str:
    kwargs.setdefault("ntp_synced", None)
    return by_name(script.run_checks(env, now=NOW, **kwargs))[name][0]


def run_main(script, env, tmp_path, **kwargs) -> int:
    """`main` con entorno inyectado, sin `.env` y sin preguntarle nada al sistema operativo."""
    kwargs.setdefault("env_file", tmp_path / "no.env")
    return script.main([], environ=env, now=NOW, **kwargs)


def test_un_entorno_correcto_no_falla(script, env, tmp_path, capsys):
    code = run_main(script, env, tmp_path, ntp_synced=True)
    out = capsys.readouterr().out
    assert code == 0
    assert "FALLA" not in out
    assert out.count("OK") >= 6


def test_cada_punto_sale_en_su_propia_linea_con_ok_o_falla(script, env, tmp_path, capsys):
    del env["TELEGRAM_BOT_TOKEN"]
    run_main(script, env, tmp_path, ntp_synced=True)
    lines = capsys.readouterr().out.strip().splitlines()
    assert all(line.split(" ")[0] in {"OK", "FALLA", "AVISO"} for line in lines), lines
    assert sum(line.startswith("FALLA") for line in lines) == 1


def test_python_menor_a_3_11_falla(script, env):
    assert status_of(script, "Python", env, python_version=(3, 10, 12)) == "FALLA"
    assert status_of(script, "Python", env, python_version=(3, 11, 0)) == "OK"
    assert status_of(script, "Python", env, python_version=(3, 12, 4)) == "OK"


def test_zona_horaria_valida(script, env):
    assert status_of(script, "Zona horaria", env) == "OK"


def test_zona_horaria_invalida_o_ausente_falla(script, env):
    env["TZ_NAME"] = "Marte/Olimpo"
    assert status_of(script, "Zona horaria", env) == "FALLA"
    env["TZ_NAME"] = ""
    assert status_of(script, "Zona horaria", env) == "FALLA"
    del env["TZ_NAME"]
    assert status_of(script, "Zona horaria", env) == "FALLA"


def test_falta_tzdata_falla(script, env):
    def missing(name):
        raise script.PackageNotFoundError(name)

    assert status_of(script, "tzdata", env, version_of=missing) == "FALLA"
    assert status_of(script, "tzdata", env, version_of=lambda name: "2026.5") == "OK"


def test_la_base_en_una_carpeta_que_no_existe_esta_ok_y_no_crea_nada(script, env, tmp_path):
    assert status_of(script, "Base de datos", env) == "OK"
    assert not (tmp_path / "data").exists()


def test_la_base_en_una_carpeta_existente_escribible_no_deja_archivos(script, env, tmp_path):
    (tmp_path / "data").mkdir()
    assert status_of(script, "Base de datos", env) == "OK"
    assert list((tmp_path / "data").iterdir()) == []


def test_la_base_en_una_ruta_imposible_falla(script, env, tmp_path):
    blocker = tmp_path / "archivo"
    blocker.write_text("x")
    env["DB_PATH"] = str(blocker / "sub" / "asistente.db")  # «carpeta» que es un archivo
    status, detail = by_name(script.run_checks(env, now=NOW, ntp_synced=None))["Base de datos"]
    assert status == "FALLA"
    assert "no es una carpeta" in detail


def test_una_base_que_es_una_carpeta_falla(script, env, tmp_path):
    folder = tmp_path / "asistente.db"
    folder.mkdir()
    env["DB_PATH"] = str(folder)
    assert status_of(script, "Base de datos", env) == "FALLA"


def test_la_base_sin_permiso_de_escritura_falla(script, env, tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()

    def deny(*args, **kwargs):
        raise PermissionError("sin permiso")

    monkeypatch.setattr(script.tempfile, "TemporaryFile", deny)
    assert status_of(script, "Base de datos", env) == "FALLA"


def test_las_variables_faltantes_se_nombran_pero_nunca_se_imprimen_valores(
    script, env, tmp_path, capsys
):
    del env["ALLOWED_USER_ID"]
    env["CURRENCY_CODE"] = ""
    code = run_main(script, env, tmp_path, ntp_synced=True)
    out = capsys.readouterr().out
    assert code == 1
    assert "ALLOWED_USER_ID" in out and "CURRENCY_CODE" in out
    assert SECRET not in out


def test_con_todo_presente_ningun_valor_aparece_en_la_salida(script, env, tmp_path, capsys):
    env["ASSISTANT_ANTHROPIC_KEY"] = "sk-ant-ULTRASECRETA"
    env["TYPESAFE_API_KEY"] = "ts-OTRA-SECRETA"
    run_main(script, env, tmp_path, ntp_synced=True)
    captured = capsys.readouterr()
    shown = captured.out + captured.err
    for secret in (SECRET, "sk-ant-ULTRASECRETA", "ts-OTRA-SECRETA", env["DB_PATH"]):
        assert secret not in shown


def test_un_valor_invalido_dice_cual_variable_sin_su_valor(script, env, tmp_path, capsys):
    env["ALLOWED_USER_ID"] = "no-es-un-numero-SECRETO"
    code = run_main(script, env, tmp_path, ntp_synced=True)
    out = capsys.readouterr().out
    assert code == 1
    assert "ALLOWED_USER_ID" in out
    assert "no-es-un-numero-SECRETO" not in out


def test_paquetes_faltantes_fallan_y_se_nombran(script, env, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("# nota\nhttpx==0.28.1\npython-telegram-bot[job-queue]==22.8\n\nfalta==1.0\n")

    def version_of(name):
        if name == "falta":
            raise script.PackageNotFoundError(name)
        return {"httpx": "0.28.1", "python-telegram-bot": "22.8", "tzdata": "2026.5"}[name]

    status, detail = by_name(
        script.run_checks(env, now=NOW, requirements=req, version_of=version_of, ntp_synced=None)
    )["Paquetes"]
    assert status == "FALLA"
    assert "falta" in detail and "httpx" not in detail


def test_paquete_con_otra_version_es_aviso_no_falla(script, env, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("httpx==0.28.1\n")
    status, detail = by_name(
        script.run_checks(
            env, now=NOW, requirements=req, version_of=lambda name: "0.27.0", ntp_synced=None
        )
    )["Paquetes"]
    assert status == "AVISO" and "httpx" in detail


def test_paquetes_al_dia_esta_ok(script, env, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("httpx==0.28.1\npython-telegram-bot[job-queue]==22.8\n")
    versions = {"httpx": "0.28.1", "python-telegram-bot": "22.8", "tzdata": "2026.5"}
    results = by_name(
        script.run_checks(
            env, now=NOW, requirements=req, version_of=versions.__getitem__, ntp_synced=None
        )
    )
    assert results["Paquetes"][0] == "OK"


def test_el_requirements_real_se_puede_leer(script):
    pairs = script.required_packages(script.REQUIREMENTS)
    assert ("python-telegram-bot", "22.8") in pairs
    assert all(name and version for name, version in pairs)


def test_reloj_razonable_es_ok(script, env):
    assert status_of(script, "Reloj", env) == "OK"


def test_reloj_anterior_a_la_fecha_minima_es_aviso(script, env):
    old = datetime(2024, 1, 1, tzinfo=UTC)
    results = by_name(script.run_checks(env, now=old, ntp_synced=None))
    assert results["Reloj"][0] == "AVISO"


def test_reloj_detras_de_la_ultima_actividad_de_la_base_es_aviso(script, env, tmp_path):
    from asistente import db

    db.open_db(tmp_path / "data" / "asistente.db").close()
    behind = datetime.now(UTC) - timedelta(days=3)  # dice que es antes de migrar
    behind = max(behind, script.MIN_PLAUSIBLE_UTC + timedelta(days=1))
    results = by_name(script.run_checks(env, now=behind, ntp_synced=None))
    assert results["Reloj"][0] == "AVISO"


def test_reloj_con_la_base_al_dia_es_ok(script, env, tmp_path):
    from asistente import db

    db.open_db(tmp_path / "data" / "asistente.db").close()
    later = max(datetime.now(UTC), script.MIN_PLAUSIBLE_UTC) + timedelta(hours=1)
    assert by_name(script.run_checks(env, now=later, ntp_synced=None))["Reloj"][0] == "OK"


def test_reloj_sin_sincronizar_es_aviso(script, env):
    assert status_of(script, "Reloj", env, ntp_synced=False) == "AVISO"
    assert status_of(script, "Reloj", env, ntp_synced=True) == "OK"


def test_un_aviso_no_hace_fallar_el_programa(script, env, tmp_path, capsys):
    code = run_main(script, env, tmp_path, ntp_synced=False)
    assert code == 0
    assert "AVISO" in capsys.readouterr().out


def test_comentarios_al_final_de_linea_en_el_env_son_falla(script, env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=abc # mi token\nTZ_NAME=UTC\n# solo comentario\n")
    status, detail = by_name(script.run_checks(env, now=NOW, env_file=env_file, ntp_synced=None))[
        "Archivo .env"
    ]
    assert status == "FALLA"
    assert "TELEGRAM_BOT_TOKEN" in detail
    assert "abc" not in detail and "mi token" not in detail
    assert "TZ_NAME" not in detail


def test_env_con_comillas_y_hash_dentro_no_falla(script, env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('A="uno # dos"\nB=x#y\n# nota\n\nexport C=3\n')
    results = by_name(script.run_checks(env, now=NOW, env_file=env_file, ntp_synced=None))
    assert results["Archivo .env"][0] == "OK"


def test_sin_archivo_env_esta_ok_si_las_variables_vienen_del_entorno(script, env, tmp_path):
    results = by_name(
        script.run_checks(env, now=NOW, env_file=tmp_path / "no.env", ntp_synced=None)
    )
    assert results["Archivo .env"][0] == "OK"


def test_ntp_sin_timedatectl_es_desconocido(script, monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda name: None)
    assert script.ntp_synchronized() is None


def test_ntp_lee_la_salida_de_timedatectl(script, monkeypatch):
    class Done:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0

    monkeypatch.setattr(script.shutil, "which", lambda name: "/usr/bin/timedatectl")
    monkeypatch.setattr(script.subprocess, "run", lambda *a, **k: Done("yes\n"))
    assert script.ntp_synchronized() is True
    monkeypatch.setattr(script.subprocess, "run", lambda *a, **k: Done("no\n"))
    assert script.ntp_synchronized() is False
    monkeypatch.setattr(script.subprocess, "run", lambda *a, **k: Done("raro\n"))
    assert script.ntp_synchronized() is None


def test_el_script_no_usa_red():
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("socket", "urllib", "httpx", "requests", "ntplib"):
        assert f"import {forbidden}" not in text
