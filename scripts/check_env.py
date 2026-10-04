"""Verifica que el entorno esté listo para arrancar el bot (igual en Windows y en Linux).

Uso (desde la raíz del repositorio, con el entorno virtual activado):
    python scripts/check_env.py

Imprime una línea por punto, que empieza con OK, AVISO o FALLA. Termina con código 0 si ningún
punto falló (un AVISO no hace fallar) y con código 1 si alguno falló. Nunca imprime el valor de
una variable de entorno: solo sus nombres. No usa red ni escribe en la base real.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asistente.config import REQUIRED_VARS, ConfigError, load_settings  # noqa: E402
from asistente.textio import force_utf8_output  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
MIN_PYTHON = (3, 11)
DEFAULT_DB_PATH = "data/asistente.db"

# PISO fijo: un reloj anterior a esta fecha casi seguro está mal (una Raspberry Pi sin pila arranca
# con la última hora guardada hasta que NTP la corrige). La señal principal es `timedatectl` (NTP)
# y la fecha del último commit; esta constante solo cubre cuando no se pueden consultar.
MIN_PLAUSIBLE_UTC = datetime(2026, 10, 1, tzinfo=UTC)
CLOCK_TOLERANCE = timedelta(minutes=5)

OK, WARN, FAIL = "OK", "AVISO", "FALLA"
_UNSET = object()
_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^\s;#]+)")


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str


def check_python(python_version: Sequence[int]) -> Result:
    found = ".".join(str(part) for part in python_version[:3])
    if tuple(python_version[:2]) >= MIN_PYTHON:
        return Result("Python", OK, found)
    need = ".".join(str(part) for part in MIN_PYTHON)
    return Result("Python", FAIL, f"se necesita {need} o más y hay {found}")


def check_tzdata(version_of: Callable[[str], str]) -> Result:
    try:
        return Result("tzdata", OK, version_of("tzdata"))
    except PackageNotFoundError:
        return Result("tzdata", FAIL, "no está instalado (pip install -r requirements.txt)")


def check_timezone(environ: Mapping[str, str]) -> Result:
    name = (environ.get("TZ_NAME") or "").strip()
    if not name:
        return Result("Zona horaria", FAIL, "falta TZ_NAME")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return Result("Zona horaria", FAIL, "TZ_NAME no es una zona IANA válida")
    return Result("Zona horaria", OK, "TZ_NAME es una zona válida")


def check_variables(environ: Mapping[str, str]) -> Result:
    """Nombra lo que falta o es inválido; nunca el valor."""
    missing = [name for name in REQUIRED_VARS if not (environ.get(name) or "").strip()]
    if missing:
        return Result("Variables", FAIL, "faltan: " + ", ".join(missing))
    try:
        load_settings(environ)
    except ConfigError as exc:
        variable = str(exc).split()[0]  # los mensajes empiezan con el nombre de la variable
        return Result("Variables", FAIL, f"{variable} tiene un valor inválido")
    return Result("Variables", OK, "las obligatorias están presentes y son válidas")


def db_file(environ: Mapping[str, str]) -> Path:
    return Path((environ.get("DB_PATH") or "").strip() or DEFAULT_DB_PATH)


def check_database(environ: Mapping[str, str]) -> Result:
    """¿Se podrá escribir la base? No crea carpetas ni deja archivos."""
    path = db_file(environ)
    if path.is_dir():
        return Result("Base de datos", FAIL, "DB_PATH apunta a una carpeta")
    folder = path.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    if not folder.is_dir():
        return Result("Base de datos", FAIL, "una parte de la ruta de DB_PATH no es una carpeta")
    if path.exists() and not os.access(path, os.W_OK):
        return Result("Base de datos", FAIL, "el archivo de la base no se puede escribir")
    try:
        with tempfile.TemporaryFile(dir=folder):  # se borra solo al cerrarse
            pass
    except OSError:
        return Result("Base de datos", FAIL, "no se puede escribir en la carpeta de la base")
    if path.parent.exists():
        return Result("Base de datos", OK, "la carpeta de la base es escribible")
    return Result("Base de datos", OK, "la carpeta se creará al arrancar y es escribible")


def required_packages(requirements: Path) -> list[tuple[str, str]]:
    """Pares (paquete, versión fijada) de un requirements.txt; ignora comentarios y opciones."""
    pairs = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = _REQUIREMENT.match(line.strip())
        if match:
            pairs.append((match.group(1), match.group(2)))
    return pairs


def check_packages(requirements: Path, version_of: Callable[[str], str]) -> Result:
    missing, different = [], []
    for name, pinned in required_packages(requirements):
        try:
            installed = version_of(name)
        except PackageNotFoundError:
            missing.append(name)
            continue
        if installed != pinned:
            different.append(name)
    if missing:
        return Result("Paquetes", FAIL, "faltan: " + ", ".join(missing))
    if different:
        return Result("Paquetes", WARN, "otra versión que la fijada: " + ", ".join(different))
    return Result("Paquetes", OK, "todos los de requirements.txt, en su versión")


def check_env_file(env_file: Path) -> Result:
    """systemd no admite comentarios al final de línea: los tomaría como parte del valor."""
    if not env_file.is_file():
        return Result("Archivo .env", OK, "no hay .env (las variables vienen del entorno)")
    flagged = []
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if value[:1] in ("'", '"'):
            continue
        if re.search(r"\s#", value):
            flagged.append(key.removeprefix("export ").strip())
    if flagged:
        return Result(
            "Archivo .env",
            FAIL,
            "comentario al final de línea (quítalo o muévelo a otra línea) en: "
            + ", ".join(flagged),
        )
    return Result("Archivo .env", OK, "sin comentarios al final de línea")


def ntp_synchronized() -> bool | None:
    """¿El sistema dice estar sincronizado por NTP? `None` si no se puede saber (p. ej. Windows)."""
    if not shutil.which("timedatectl"):
        return None
    try:
        done = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {"yes": True, "no": False}.get(done.stdout.strip())


def last_commit_time(root: Path = ROOT) -> datetime | None:
    """Fecha del último commit (UTC) si git está disponible; el reloj no puede ir detrás de ella.

    `None` si no hay git, no es un repositorio o la salida no se entiende.
    """
    if not shutil.which("git"):
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return datetime.fromtimestamp(int(done.stdout.strip()), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _latest_database_activity(path: Path) -> datetime | None:
    """La marca de tiempo más reciente que ya guarda la base (solo lectura), si se puede leer."""
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT MAX(applied_at) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(row[0])
    except ValueError:
        return None


def check_clock(
    now: datetime,
    db_path: Path,
    ntp_synced: bool | None,
    commit_time: datetime | None = None,
) -> Result:
    problems = []
    if now < MIN_PLAUSIBLE_UTC:
        problems.append("la fecha del sistema es anterior a la de esta versión")
    if commit_time is not None and now + CLOCK_TOLERANCE < commit_time:
        problems.append("el reloj va detrás de la fecha del último commit")
    last = _latest_database_activity(db_path)
    if last is not None and now + CLOCK_TOLERANCE < last:
        problems.append("el reloj va detrás de lo último que registró la base")
    if ntp_synced is False:
        problems.append("el sistema no está sincronizado por NTP")
    if problems:
        return Result("Reloj", WARN, "; ".join(problems))
    return Result("Reloj", OK, "fecha razonable" + (" y NTP sincronizado" if ntp_synced else ""))


def run_checks(
    environ: Mapping[str, str],
    now: datetime | None = None,
    python_version: Sequence[int] | None = None,
    version_of: Callable[[str], str] = version,
    requirements: Path = REQUIREMENTS,
    env_file: Path | None = None,
    ntp_synced: object = _UNSET,
    commit_time: object = _UNSET,
) -> list[Result]:
    if ntp_synced is _UNSET:
        ntp_synced = ntp_synchronized()
    if commit_time is _UNSET:
        commit_time = last_commit_time()
    return [
        check_python(python_version or sys.version_info),
        check_tzdata(version_of),
        check_timezone(environ),
        check_variables(environ),
        check_database(environ),
        check_packages(requirements, version_of),
        check_env_file(env_file or Path.cwd() / ".env"),
        check_clock(
            now or datetime.now(UTC),
            db_file(environ),
            ntp_synced,  # type: ignore[arg-type]
            commit_time,  # type: ignore[arg-type]
        ),
    ]


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    env_file: Path | None = None,
    ntp_synced: object = _UNSET,
) -> int:
    force_utf8_output()
    env_file = env_file or Path.cwd() / ".env"
    if environ is None:
        load_dotenv(env_file)  # solo el del directorio actual, como main.py
        environ = dict(os.environ)
    results = run_checks(environ, now=now, env_file=env_file, ntp_synced=ntp_synced)
    for result in results:
        print(f"{result.status} {result.name}: {result.detail}")
    return 1 if any(result.status == FAIL for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
