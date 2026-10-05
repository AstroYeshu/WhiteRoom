"""Hook de pre-commit versionado y su instalador.

El hook se prueba en un repositorio temporal con un `python` falso (un script de shell que anota lo
que le piden y sale con el código que se le indica): nunca corre la suite real dentro de una prueba.
"""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".githooks" / "pre-commit"
INSTALLER = ROOT / "scripts" / "install_hooks.py"
SH = shutil.which("sh")
needs_sh = pytest.mark.skipif(SH is None, reason="hace falta sh (Git Bash en Windows)")

FAKE_PYTHON = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$2" in
  pytest) exit "${FAKE_PYTEST_CODE:-0}" ;;
  ruff) exit "${FAKE_RUFF_CODE:-0}" ;;
esac
exit 99
"""


def load_installer():
    spec = importlib.util.spec_from_file_location("install_hooks", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.fixture(autouse=True)
def aislar_la_configuracion_de_git(tmp_path_factory, monkeypatch):
    """Ninguna prueba puede tocar la configuración real de git: la global va a un archivo
    temporal y, al terminar, se comprueba (y se deshace) que el repositorio real siga igual."""
    fake_global = tmp_path_factory.mktemp("gitconfig") / "global"
    fake_global.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(fake_global))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    before = git(ROOT, "config", "--local", "--get", "core.hooksPath").stdout.strip()
    yield fake_global
    after = git(ROOT, "config", "--local", "--get", "core.hooksPath").stdout.strip()
    if after != before:
        git(ROOT, "config", "--local", "--unset", "core.hooksPath")
        pytest.fail("una prueba cambió core.hooksPath del repositorio REAL (ya se deshizo)")


@pytest.fixture
def repo(tmp_path) -> Path:
    git(tmp_path, "init", "-q")
    return tmp_path


def make_repo_with_hook(repo: Path, venv_dir: str) -> Path:
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")
    python = repo / "venv" / venv_dir / "python"
    python.parent.mkdir(parents=True)
    python.write_text(FAKE_PYTHON, newline="\n")
    return python


def run_hook(repo: Path, **codes: int) -> tuple[subprocess.CompletedProcess, list[str]]:
    log = repo / "fake.log"
    env = {**os.environ, "FAKE_LOG": str(log)}
    env.update({f"FAKE_{name.upper()}_CODE": str(code) for name, code in codes.items()})
    done = subprocess.run(
        [SH, ".githooks/pre-commit"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done, log.read_text().splitlines() if log.exists() else []


# --- El hook -------------------------------------------------------------------------------------


def test_el_hook_existe_y_empieza_con_shebang_y_lf():
    raw = HOOK.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r\n" not in raw


def test_gitattributes_fuerza_lf_en_los_hooks():
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert ".githooks/* text eol=lf" in lines


@needs_sh
@pytest.mark.parametrize("venv_dir", ["bin", "Scripts"])
def test_con_todo_en_verde_corre_pytest_y_ruff_y_deja_pasar(repo, venv_dir):
    make_repo_with_hook(repo, venv_dir)
    done, calls = run_hook(repo)
    assert done.returncode == 0, done.stderr
    assert calls == ["-m pytest -q", "-m ruff check ."]


@needs_sh
def test_si_pytest_falla_bloquea_el_commit(repo):
    make_repo_with_hook(repo, "bin")
    done, calls = run_hook(repo, pytest=1)
    assert done.returncode != 0
    assert calls[0] == "-m pytest -q"
    assert "pytest" in done.stderr


@needs_sh
def test_si_ruff_falla_bloquea_el_commit(repo):
    make_repo_with_hook(repo, "bin")
    done, calls = run_hook(repo, ruff=1)
    assert done.returncode != 0
    assert "-m ruff check ." in calls
    assert "ruff" in done.stderr


@needs_sh
def test_corre_ruff_aunque_pytest_falle_para_mostrar_todo(repo):
    make_repo_with_hook(repo, "bin")
    _, calls = run_hook(repo, pytest=1, ruff=1)
    assert calls == ["-m pytest -q", "-m ruff check ."]


@needs_sh
def test_el_codigo_de_salida_de_cada_uno_se_mide_por_separado(repo):
    """Un 1 de pytest no se pierde porque ruff salga bien después (y al revés)."""
    make_repo_with_hook(repo, "bin")
    assert run_hook(repo, pytest=2, ruff=0)[0].returncode != 0
    assert run_hook(repo, pytest=0, ruff=3)[0].returncode != 0


def run_without_venv(repo: Path) -> subprocess.CompletedProcess:
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")
    return subprocess.run(
        [SH, ".githooks/pre-commit"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@needs_sh
def test_sin_venv_bloquea_el_commit(repo):
    assert run_without_venv(repo).returncode != 0


@needs_sh
def test_sin_venv_explica_que_falta_el_entorno_virtual(repo):
    assert "entorno virtual" in run_without_venv(repo).stderr


def run_from_subdir(repo: Path) -> tuple[subprocess.CompletedProcess, Path]:
    make_repo_with_hook(repo, "bin")
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    log = repo / "fake.log"
    done = subprocess.run(
        [SH, str(repo / ".githooks" / "pre-commit")],
        cwd=sub,
        env={**os.environ, "FAKE_LOG": str(log)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done, log


@needs_sh
def test_desde_un_subdirectorio_el_hook_encuentra_el_venv_y_pasa(repo):
    done, _ = run_from_subdir(repo)
    assert done.returncode == 0, done.stderr


@needs_sh
def test_desde_un_subdirectorio_el_hook_corre_las_dos_herramientas(repo):
    _, log = run_from_subdir(repo)
    assert log.read_text().splitlines() == ["-m pytest -q", "-m ruff check ."]


@needs_sh
def test_si_las_dos_fallan_se_informan_las_dos(repo):
    make_repo_with_hook(repo, "bin")
    done, _ = run_hook(repo, pytest=1, ruff=1)
    assert "pytest falló" in done.stderr and "ruff falló" in done.stderr


# --- El instalador -------------------------------------------------------------------------------


def test_el_instalador_configura_hookspath_en_el_repositorio_dado(repo):
    installer = load_installer()
    (repo / ".githooks").mkdir()
    assert installer.main([str(repo)]) == 0
    assert git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == ".githooks"


def test_el_instalador_no_toca_la_configuracion_global(repo, aislar_la_configuracion_de_git):
    installer = load_installer()
    (repo / ".githooks").mkdir()
    installer.main([str(repo)])
    assert aislar_la_configuracion_de_git.read_text() == ""
    assert git(repo, "config", "--global", "--get", "core.hooksPath").stdout.strip() == ""


def test_el_instalador_es_idempotente(repo):
    installer = load_installer()
    (repo / ".githooks").mkdir()
    assert installer.main([str(repo)]) == 0
    assert installer.main([str(repo)]) == 0
    assert git(repo, "config", "--local", "--get-all", "core.hooksPath").stdout.split() == [
        ".githooks"
    ]


def test_el_instalador_falla_si_no_es_un_repositorio(tmp_path, capsys):
    installer = load_installer()
    (tmp_path / ".githooks").mkdir()
    assert installer.main([str(tmp_path)]) != 0
    assert "repositorio" in capsys.readouterr().err
    assert not (tmp_path / ".git").exists()


def test_el_instalador_falla_si_la_ruta_no_existe(tmp_path, capsys):
    installer = load_installer()
    assert installer.main([str(tmp_path / "no-existe")]) != 0
    assert "repositorio" in capsys.readouterr().err


def test_el_instalador_falla_si_falta_la_carpeta_de_hooks(repo, capsys):
    installer = load_installer()
    assert installer.main([str(repo)]) != 0
    assert ".githooks" in capsys.readouterr().err


def test_sin_carpeta_de_hooks_no_se_configura_nada(repo):
    load_installer().main([str(repo)])
    assert git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == ""


def test_el_instalador_por_defecto_apunta_a_este_repositorio():
    installer = load_installer()
    assert installer.default_root() == ROOT


@needs_sh
def test_un_commit_real_se_bloquea_con_el_hook_instalado(repo):
    """De punta a punta en un repositorio temporal: el commit falla si pytest falla."""
    make_repo_with_hook(repo, "bin")
    load_installer().main([str(repo)])
    (repo / "a.txt").write_text("x")
    git(repo, "add", "a.txt")
    env = {
        **os.environ,
        "FAKE_LOG": str(repo / "fake.log"),
        "FAKE_PYTEST_CODE": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    blocked = subprocess.run(
        ["git", "commit", "-m", "x"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert blocked.returncode != 0
    env["FAKE_PYTEST_CODE"] = "0"
    allowed = subprocess.run(
        ["git", "commit", "-m", "x"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert allowed.returncode == 0, allowed.stderr
