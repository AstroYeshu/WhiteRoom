"""`tests/shell.py::find_sh`: encuentra `sh` aunque Git Bash no esté en el PATH (PowerShell).

Sin esto, las 29 pruebas de hooks se omitían en PowerShell y solo corrían desde Git Bash.
"""

from pathlib import Path

from tests.shell import find_sh


def fake_git_install(root: Path, sh_relative: str, git_relative: str) -> Path:
    sh = root / sh_relative
    sh.parent.mkdir(parents=True)
    sh.write_text("", encoding="utf-8")
    git = root / git_relative
    git.parent.mkdir(parents=True, exist_ok=True)
    git.write_text("", encoding="utf-8")
    return git


def which_only(**found: str):
    return lambda name: found.get(name)


def test_si_sh_esta_en_el_path_se_usa_ese(tmp_path):
    assert find_sh(which_only(sh="/usr/bin/sh")) == "/usr/bin/sh"


def test_sin_sh_ni_git_no_hay_shell():
    assert find_sh(which_only()) is None


def test_sin_sh_en_el_path_lo_busca_junto_a_git_cmd(tmp_path):
    git = fake_git_install(tmp_path / "Git", "bin/sh.exe", "cmd/git.exe")
    assert find_sh(which_only(git=str(git))) == str(tmp_path / "Git" / "bin" / "sh.exe")


def test_lo_busca_en_usr_bin_junto_a_git(tmp_path):
    git = fake_git_install(tmp_path / "Git", "usr/bin/sh.exe", "cmd/git.exe")
    assert find_sh(which_only(git=str(git))) == str(tmp_path / "Git" / "usr" / "bin" / "sh.exe")


def test_lo_busca_cuando_git_vive_en_mingw64_bin(tmp_path):
    git = fake_git_install(tmp_path / "Git", "bin/sh.exe", "mingw64/bin/git.exe")
    assert find_sh(which_only(git=str(git))) == str(tmp_path / "Git" / "bin" / "sh.exe")


def test_si_git_no_tiene_sh_cerca_no_adivina(tmp_path):
    git = fake_git_install(tmp_path / "Git", "otra/cosa.exe", "cmd/git.exe")
    assert find_sh(which_only(git=str(git))) is None


def test_el_sh_del_path_gana_al_de_git(tmp_path):
    git = fake_git_install(tmp_path / "Git", "bin/sh.exe", "cmd/git.exe")
    assert find_sh(which_only(sh="/usr/bin/sh", git=str(git))) == "/usr/bin/sh"
