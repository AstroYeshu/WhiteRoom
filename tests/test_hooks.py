"""Hooks de pre-commit (rapido) y pre-push (completo) versionados, y su instalador.

El hook se prueba en un repositorio temporal con un `python` falso (un script de shell que anota lo
que le piden y sale con el código que se le indica): nunca corre la suite real dentro de una prueba.
"""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.shell import find_sh

# Lanzan `sh` y git decenas de veces (~11 s): van en la suite completa (pre-push), no en la rapida.
pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / ".githooks"
INSTALLER = ROOT / "scripts" / "install_hooks.py"
SH = find_sh()
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


def make_repo_with_hook(repo: Path, venv_dir: str, hook: str = "pre-commit") -> Path:
    (repo / ".githooks").mkdir(exist_ok=True)
    shutil.copy(HOOKS_DIR / hook, repo / ".githooks" / hook)
    python = repo / "venv" / venv_dir / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text(FAKE_PYTHON, newline="\n")
    return python


def run_hook(
    repo: Path, hook: str = "pre-commit", **codes: int
) -> tuple[subprocess.CompletedProcess, list[str]]:
    log = repo / "fake.log"
    env = {**os.environ, "FAKE_LOG": str(log)}
    env.update({f"FAKE_{name.upper()}_CODE": str(code) for name, code in codes.items()})
    done = subprocess.run(
        [SH, f".githooks/{hook}"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done, log.read_text().splitlines() if log.exists() else []


RUFF = "-m ruff check ."
RAPIDA = "-m pytest -q -m not slow"  # `echo "$@"` quita las comillas de "not slow"
COMPLETA = "-m pytest -q"
BOTH_HOOKS = ["pre-commit", "pre-push"]

# --- Los dos hooks (comunes) ---------------------------------------------------------------------


@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_el_hook_existe_y_empieza_con_shebang_y_lf(hook):
    raw = (HOOKS_DIR / hook).read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r\n" not in raw


def test_gitattributes_fuerza_lf_en_los_hooks():
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert ".githooks/* text eol=lf" in lines


@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_los_hooks_estan_versionados_como_ejecutables(hook):
    """En la Raspberry Pi (Linux) git ignora un hook sin el bit de ejecucion."""
    listed = git(ROOT, "ls-files", "-s", f".githooks/{hook}").stdout
    assert listed.startswith("100755"), listed


def run_without_venv(repo: Path, hook: str) -> subprocess.CompletedProcess:
    (repo / ".githooks").mkdir()
    shutil.copy(HOOKS_DIR / hook, repo / ".githooks" / hook)
    return subprocess.run(
        [SH, f".githooks/{hook}"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_sin_venv_bloquea(repo, hook):
    assert run_without_venv(repo, hook).returncode != 0


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_sin_venv_explica_que_falta_el_entorno_virtual(repo, hook):
    assert "entorno virtual" in run_without_venv(repo, hook).stderr


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
@pytest.mark.parametrize("venv_dir", ["bin", "Scripts"])
def test_con_todo_en_verde_deja_pasar_en_linux_y_en_windows(repo, hook, venv_dir):
    make_repo_with_hook(repo, venv_dir, hook)
    done, calls = run_hook(repo, hook)
    assert done.returncode == 0, done.stderr
    assert calls


def run_from_subdir(repo: Path, hook: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    make_repo_with_hook(repo, "bin", hook)
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    log = repo / "fake.log"
    done = subprocess.run(
        [SH, str(repo / ".githooks" / hook)],
        cwd=sub,
        env={**os.environ, "FAKE_LOG": str(log)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done, log.read_text().splitlines() if log.exists() else []


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_desde_un_subdirectorio_el_hook_encuentra_el_venv_y_pasa(repo, hook):
    done, calls = run_from_subdir(repo, hook)
    assert done.returncode == 0, done.stderr
    assert calls


EXPECTED_CALLS = {"pre-commit": [RUFF, RAPIDA], "pre-push": [COMPLETA]}


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_desde_un_subdirectorio_el_hook_corre_sus_herramientas(repo, hook):
    _, calls = run_from_subdir(repo, hook)
    assert calls == EXPECTED_CALLS[hook]


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_con_el_venv_de_windows_corre_sus_herramientas(repo, hook):
    make_repo_with_hook(repo, "Scripts", hook)
    _, calls = run_hook(repo, hook)
    assert calls == EXPECTED_CALLS[hook]


@needs_sh
@pytest.mark.parametrize("hook", BOTH_HOOKS)
def test_sin_venv_sale_con_codigo_1_y_dice_que_bloquea(repo, hook):
    done = run_without_venv(repo, hook)
    assert done.returncode == 1
    assert "bloqueado" in done.stderr


# --- pre-commit: ruff + suite rapida -----------------------------------------------------------


@needs_sh
def test_pre_commit_corre_ruff_y_la_suite_rapida_sin_las_lentas(repo):
    make_repo_with_hook(repo, "bin")
    done, calls = run_hook(repo)
    assert done.returncode == 0, done.stderr
    assert calls == [RUFF, RAPIDA]


@needs_sh
def test_pre_commit_no_corre_la_suite_completa(repo):
    make_repo_with_hook(repo, "bin")
    _, calls = run_hook(repo)
    assert COMPLETA not in calls  # la completa es del pre-push


@needs_sh
def test_si_pytest_falla_bloquea_el_commit(repo):
    make_repo_with_hook(repo, "bin")
    done, calls = run_hook(repo, pytest=1)
    assert done.returncode != 0
    assert RAPIDA in calls
    assert "pytest" in done.stderr


@needs_sh
def test_si_ruff_falla_bloquea_el_commit(repo):
    make_repo_with_hook(repo, "bin")
    done, calls = run_hook(repo, ruff=1)
    assert done.returncode != 0
    assert RUFF in calls
    assert "ruff" in done.stderr


@needs_sh
def test_corre_las_dos_aunque_una_falle_para_mostrar_todo(repo):
    make_repo_with_hook(repo, "bin")
    _, calls = run_hook(repo, pytest=1, ruff=1)
    assert calls == [RUFF, RAPIDA]


@needs_sh
def test_el_codigo_de_salida_de_cada_uno_se_mide_por_separado(repo):
    """Un 1 de pytest no se pierde porque ruff salga bien despues (y al reves)."""
    make_repo_with_hook(repo, "bin")
    assert run_hook(repo, pytest=2, ruff=0)[0].returncode != 0
    assert run_hook(repo, pytest=0, ruff=3)[0].returncode != 0


@needs_sh
def test_si_las_dos_fallan_se_informan_las_dos(repo):
    make_repo_with_hook(repo, "bin")
    done, _ = run_hook(repo, pytest=1, ruff=1)
    assert "pytest falló" in done.stderr and "ruff falló" in done.stderr


# --- pre-push: suite completa ------------------------------------------------------------------


@needs_sh
def test_pre_push_corre_la_suite_completa_incluidas_las_lentas(repo):
    make_repo_with_hook(repo, "bin", "pre-push")
    done, calls = run_hook(repo, "pre-push")
    assert done.returncode == 0, done.stderr
    assert calls == [COMPLETA]  # sin `-m "not slow"`


@needs_sh
def test_si_pytest_falla_bloquea_el_push(repo):
    make_repo_with_hook(repo, "bin", "pre-push")
    done, _ = run_hook(repo, "pre-push", pytest=1)
    assert done.returncode != 0
    assert "pytest falló" in done.stderr


@needs_sh
def test_pre_push_no_filtra_por_marcador_ni_corre_ruff(repo):
    make_repo_with_hook(repo, "bin", "pre-push")
    _, calls = run_hook(repo, "pre-push")
    assert all("slow" not in call for call in calls)
    assert all("ruff" not in call for call in calls)


@needs_sh
def test_el_codigo_de_pytest_llega_tal_cual_al_push(repo):
    make_repo_with_hook(repo, "bin", "pre-push")
    assert run_hook(repo, "pre-push", pytest=5)[0].returncode == 5


# --- El instalador -------------------------------------------------------------------------------


def copy_hooks(repo: Path, *names: str) -> None:
    (repo / ".githooks").mkdir(exist_ok=True)
    for name in names or BOTH_HOOKS:
        shutil.copy(HOOKS_DIR / name, repo / ".githooks" / name)


def test_el_instalador_configura_hookspath_en_el_repositorio_dado(repo):
    installer = load_installer()
    copy_hooks(repo)
    assert installer.main([str(repo)]) == 0
    assert git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == ".githooks"


def test_el_instalador_no_toca_la_configuracion_global(repo, aislar_la_configuracion_de_git):
    installer = load_installer()
    copy_hooks(repo)
    installer.main([str(repo)])
    assert aislar_la_configuracion_de_git.read_text() == ""
    assert git(repo, "config", "--global", "--get", "core.hooksPath").stdout.strip() == ""


def test_el_instalador_es_idempotente(repo):
    installer = load_installer()
    copy_hooks(repo)
    assert installer.main([str(repo)]) == 0
    assert installer.main([str(repo)]) == 0
    assert git(repo, "config", "--local", "--get-all", "core.hooksPath").stdout.split() == [
        ".githooks"
    ]


def test_el_instalador_falla_si_no_es_un_repositorio(tmp_path, capsys):
    installer = load_installer()
    copy_hooks(tmp_path)
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


@pytest.mark.parametrize("missing", BOTH_HOOKS)
def test_el_instalador_falla_si_falta_uno_de_los_dos_hooks(repo, capsys, missing):
    installer = load_installer()
    copy_hooks(repo, *[h for h in BOTH_HOOKS if h != missing])
    assert installer.main([str(repo)]) != 0
    assert missing in capsys.readouterr().err
    assert git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == ""


def test_los_nombres_de_hooks_del_instalador_son_los_dos_versionados():
    assert set(load_installer().HOOK_NAMES) == set(BOTH_HOOKS)
    assert {p.name for p in HOOKS_DIR.iterdir()} == set(BOTH_HOOKS)


def test_el_instalador_menciona_los_dos_hooks_al_terminar(repo, capsys):
    copy_hooks(repo)
    assert load_installer().main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "pre-commit" in out and "pre-push" in out


def test_sin_carpeta_de_hooks_no_se_configura_nada(repo):
    load_installer().main([str(repo)])
    assert git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip() == ""


def test_el_instalador_por_defecto_apunta_a_este_repositorio():
    installer = load_installer()
    assert installer.default_root() == ROOT


def real_git(repo: Path, *args: str, **codes: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "FAKE_LOG": str(repo / "fake.log"),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        **codes,
    }
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@needs_sh
def test_un_commit_real_se_bloquea_con_el_hook_instalado(repo):
    """De punta a punta en un repositorio temporal: el commit falla si pytest falla."""
    make_repo_with_hook(repo, "bin", "pre-commit")
    copy_hooks(repo)
    load_installer().main([str(repo)])
    (repo / "a.txt").write_text("x")
    git(repo, "add", "a.txt")
    assert real_git(repo, "commit", "-m", "x", FAKE_PYTEST_CODE="1").returncode != 0
    allowed = real_git(repo, "commit", "-m", "x", FAKE_PYTEST_CODE="0")
    assert allowed.returncode == 0, allowed.stderr


@needs_sh
def test_un_push_real_se_bloquea_con_el_hook_instalado(repo, tmp_path_factory):
    """El commit pasa (hook rapido) pero el push se frena si la suite completa falla."""
    remote = tmp_path_factory.mktemp("remoto")
    git(remote, "init", "-q", "--bare")
    make_repo_with_hook(repo, "bin")
    copy_hooks(repo)
    load_installer().main([str(repo)])
    git(repo, "remote", "add", "origin", str(remote))
    (repo / "a.txt").write_text("x")
    git(repo, "add", "a.txt")
    assert real_git(repo, "commit", "-m", "x").returncode == 0
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    blocked = real_git(repo, "push", "origin", branch, FAKE_PYTEST_CODE="1")
    assert blocked.returncode != 0
    assert git(remote, "rev-parse", "--verify", branch).returncode != 0  # nada llego al remoto
    allowed = real_git(repo, "push", "origin", branch, FAKE_PYTEST_CODE="0")
    assert allowed.returncode == 0, allowed.stderr
    assert git(remote, "rev-parse", "--verify", branch).returncode == 0
