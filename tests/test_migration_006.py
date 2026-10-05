"""Migración 006: pone en mayúscula la primera letra de las áreas existentes (sin pisar ninguna).

Es la primera migración en Python (`006_capitalizar_areas.py`): el ejecutor de `db.py` acepta
`NNN_nombre.py` con una función `upgrade(conn)`, dentro de la misma transacción que las `.sql`.
En SQL no se puede: `upper()` de SQLite solo conoce ASCII y no hay forma de comparar sin acentos.
"""

import ast
import importlib.util
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from asistente import db


def old_database(tmp_path: Path) -> sqlite3.Connection:
    """Base con las migraciones 001..005 (las cuatro áreas iniciales, en minúscula)."""
    old = tmp_path / "migrations_old"
    old.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(path, old / path.name)
    connection = db.connect(":memory:")
    assert db.migrate(connection, old) == [1, 2, 3, 4, 5]
    return connection


def add_area(connection, name: str, archived: int = 0) -> int:
    with connection:
        cursor = connection.execute(
            "INSERT INTO areas (name, description, archived, created_at) VALUES (?, ?, ?, 'x')",
            (name, f"descripción de {name}", archived),
        )
    return cursor.lastrowid


def log(connection, pred_area, final_area) -> int:
    with connection:
        cursor = connection.execute(
            "INSERT INTO classification_log (ts_utc, text_norm, source, pred_area, final_area)"
            " VALUES ('x', 'texto norm', 'user', ?, ?)",
            (pred_area, final_area),
        )
    return cursor.lastrowid


def names(connection) -> dict[int, str]:
    return {row["id"]: row["name"] for row in connection.execute("SELECT id, name FROM areas")}


def by_name(connection) -> list[str]:
    return [row["name"] for row in connection.execute("SELECT name FROM areas ORDER BY id")]


def test_existe_el_archivo_006_y_es_el_siguiente_numero_libre():
    assert (db.MIGRATIONS_DIR / "006_capitalizar_areas.py").is_file()
    numbers = sorted(
        int(path.name.split("_")[0])
        for path in db.MIGRATIONS_DIR.iterdir()
        if path.suffix in (".sql", ".py")
    )
    assert numbers == [1, 2, 3, 4, 5, 6]


def test_aplica_solo_la_006_y_la_registra(tmp_path):
    connection = old_database(tmp_path)
    assert db.migrate(connection) == [6]
    row = connection.execute("SELECT name FROM schema_migrations WHERE version = 6").fetchone()
    assert row["name"] == "006_capitalizar_areas.py"
    assert db.migrate(connection) == []


def test_las_areas_iniciales_pasan_a_mayuscula(tmp_path):
    connection = old_database(tmp_path)
    db.migrate(connection)
    assert by_name(connection) == ["Universidad", "Proyectos", "Iglesia", "Personal"]


def test_solo_cambia_la_primera_letra_y_nada_mas_de_la_fila(tmp_path):
    connection = old_database(tmp_path)
    before = [dict(row) for row in connection.execute("SELECT * FROM areas ORDER BY id")]
    db.migrate(connection)
    after = [dict(row) for row in connection.execute("SELECT * FROM areas ORDER BY id")]
    for old, new in zip(before, after, strict=True):
        assert new["name"] == old["name"][0].upper() + old["name"][1:]
        assert {k: v for k, v in new.items() if k != "name"} == {
            k: v for k, v in old.items() if k != "name"
        }


def test_acentos_enie_y_nombres_con_mayuscula_propia(tmp_path):
    connection = old_database(tmp_path)
    ids = {
        n: add_area(connection, n) for n in ("álgebra", "ñandú", "iOS", "UNAM", "Salud", "mi casa")
    }
    db.migrate(connection)
    found = names(connection)
    assert found[ids["álgebra"]] == "Álgebra"
    assert found[ids["ñandú"]] == "Ñandú"
    assert found[ids["iOS"]] == "iOS"  # ya tiene su propia mayúscula
    assert found[ids["UNAM"]] == "UNAM"
    assert found[ids["Salud"]] == "Salud"
    assert found[ids["mi casa"]] == "Mi casa"


def test_las_areas_archivadas_tambien_se_capitalizan(tmp_path):
    connection = old_database(tmp_path)
    archived = add_area(connection, "viajes", archived=1)
    db.migrate(connection)
    row = connection.execute(
        "SELECT name, archived FROM areas WHERE id = ?", (archived,)
    ).fetchone()
    assert (row["name"], row["archived"]) == ("Viajes", 1)


def test_los_espacios_internos_no_se_tocan(tmp_path):
    connection = old_database(tmp_path)
    odd = add_area(connection, "mi  casa")
    db.migrate(connection)
    assert names(connection)[odd] == "Mi  casa"


# --- Colisiones: nunca se pisa un área ----------------------------------------------------------


def test_no_se_renombra_si_choca_con_otra_area_en_mayuscula(tmp_path):
    connection = old_database(tmp_path)
    twin = add_area(connection, "Personal")  # el UNIQUE de SQLite sí distingue mayúsculas
    db.migrate(connection)
    found = names(connection)
    assert found[4] == "personal"  # la inicial, sin tocar
    assert found[twin] == "Personal"
    assert sorted(by_name(connection)) == sorted(
        ["Universidad", "Proyectos", "Iglesia", "personal", "Personal"]
    )


def test_la_colision_ignora_los_acentos(tmp_path):
    connection = old_database(tmp_path)
    plain = add_area(connection, "Musica")
    accented = add_area(connection, "música")
    db.migrate(connection)
    found = names(connection)
    assert found[plain] == "Musica" and found[accented] == "música"


def test_la_colision_cuenta_a_las_archivadas(tmp_path):
    connection = old_database(tmp_path)
    twin = add_area(connection, "Iglesia", archived=1)
    db.migrate(connection)
    found = names(connection)
    assert found[3] == "iglesia" and found[twin] == "Iglesia"


def test_la_colision_ignora_las_mayusculas_distintas_de_la_primera_letra(tmp_path):
    connection = old_database(tmp_path)
    shout = add_area(connection, "PERSONAL")  # "personal" -> "Personal" no es IGUAL a "PERSONAL"
    db.migrate(connection)
    found = names(connection)
    assert found[4] == "personal" and found[shout] == "PERSONAL"


def test_la_colision_con_una_archivada_con_acento_y_mayusculas(tmp_path):
    connection = old_database(tmp_path)
    archived = add_area(connection, "MÚSICA", archived=1)
    live = add_area(connection, "música")
    db.migrate(connection)
    found = names(connection)
    assert found[archived] == "MÚSICA" and found[live] == "música"


def test_la_colision_de_un_area_no_impide_las_demas(tmp_path):
    connection = old_database(tmp_path)
    add_area(connection, "Personal")
    free = add_area(connection, "viajes")
    db.migrate(connection)
    found = names(connection)
    assert found[1] == "Universidad" and found[free] == "Viajes"


def test_nunca_quedan_dos_areas_con_el_mismo_nombre(tmp_path):
    connection = old_database(tmp_path)
    for name in ("Personal", "Musica", "música", "Universidad"):
        add_area(connection, name)
    db.migrate(connection)
    exact = list(connection.execute("SELECT name, COUNT(*) AS n FROM areas GROUP BY name"))
    assert all(row["n"] == 1 for row in exact)
    assert len(by_name(connection)) == 8


def test_una_area_ya_en_mayuscula_no_choca_consigo_misma(tmp_path):
    connection = old_database(tmp_path)
    own = add_area(connection, "Salud")
    db.migrate(connection)
    assert names(connection)[own] == "Salud"


# --- classification_log: pred_area y final_area siguen a los nombres ------------------------------


def test_el_registro_de_clasificacion_sigue_al_area_renombrada(tmp_path):
    connection = old_database(tmp_path)
    first = log(connection, "personal", "universidad")
    second = log(connection, None, "iglesia")
    third = log(connection, "proyectos", None)
    db.migrate(connection)
    rows = {r["id"]: r for r in connection.execute("SELECT * FROM classification_log")}
    assert (rows[first]["pred_area"], rows[first]["final_area"]) == ("Personal", "Universidad")
    assert (rows[second]["pred_area"], rows[second]["final_area"]) == (None, "Iglesia")
    assert (rows[third]["pred_area"], rows[third]["final_area"]) == ("Proyectos", None)
    assert all(r["text_norm"] == "texto norm" for r in rows.values())


def test_el_registro_no_cambia_si_el_area_no_se_renombro(tmp_path):
    connection = old_database(tmp_path)
    add_area(connection, "Personal")  # choca con la inicial: "personal" se queda como está
    kept = log(connection, "personal", "personal")
    other = log(connection, "universidad", "inventada")
    db.migrate(connection)
    rows = {r["id"]: r for r in connection.execute("SELECT * FROM classification_log")}
    assert (rows[kept]["pred_area"], rows[kept]["final_area"]) == ("personal", "personal")
    assert (rows[other]["pred_area"], rows[other]["final_area"]) == ("Universidad", "inventada")


def test_la_migracion_no_toca_tareas_notas_ni_recordatorios(tmp_path):
    connection = old_database(tmp_path)
    with connection:
        connection.execute(
            "INSERT INTO tasks (title, area_id, source_text, created_at, updated_at)"
            " VALUES ('comprar pan', 4, 'comprar pan', 'x', 'x')"
        )
        connection.execute(
            "INSERT INTO notes (text, area_id, created_at) VALUES ('una nota', 4, 'x')"
        )
    db.migrate(connection)
    task = connection.execute("SELECT title, source_text, area_id FROM tasks").fetchone()
    assert tuple(task) == ("comprar pan", "comprar pan", 4)  # sigue ligada por id
    assert connection.execute("SELECT text FROM notes").fetchone()["text"] == "una nota"


def test_una_base_nueva_sale_con_las_areas_en_mayuscula():
    connection = db.open_db(":memory:")
    assert by_name(connection) == ["Universidad", "Proyectos", "Iglesia", "Personal"]


# --- El ejecutor admite migraciones en Python -----------------------------------------------------


def write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def test_el_ejecutor_corre_una_migracion_en_python_y_la_registra(tmp_path):
    write(tmp_path, "001_t.sql", "CREATE TABLE t (n INTEGER);")
    write(
        tmp_path,
        "002_py.py",
        "def upgrade(conn):\n    conn.execute('INSERT INTO t VALUES (7)')\n",
    )
    connection = db.connect(":memory:")
    assert db.migrate(connection, tmp_path) == [1, 2]
    assert connection.execute("SELECT n FROM t").fetchone()["n"] == 7
    assert db.migrate(connection, tmp_path) == []
    row = connection.execute("SELECT name FROM schema_migrations WHERE version = 2").fetchone()
    assert row["name"] == "002_py.py"


def test_una_migracion_en_python_que_falla_no_queda_a_medias(tmp_path):
    write(tmp_path, "001_t.sql", "CREATE TABLE t (n INTEGER);")
    write(
        tmp_path,
        "002_mala.py",
        "def upgrade(conn):\n"
        "    conn.execute('INSERT INTO t VALUES (1)')\n"
        "    conn.execute('INSERT INTO no_existe VALUES (1)')\n",
    )
    connection = db.connect(":memory:")
    with pytest.raises(sqlite3.Error):
        db.migrate(connection, tmp_path)
    assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    versions = [r["version"] for r in connection.execute("SELECT version FROM schema_migrations")]
    assert versions == [1]
    assert not connection.in_transaction


def test_una_migracion_en_python_con_un_error_cualquiera_tambien_se_deshace(tmp_path):
    write(tmp_path, "001_t.sql", "CREATE TABLE t (n INTEGER);")
    write(
        tmp_path,
        "002_mala.py",
        "def upgrade(conn):\n    conn.execute('INSERT INTO t VALUES (1)')\n"
        "    raise RuntimeError('x')\n",
    )
    connection = db.connect(":memory:")
    with pytest.raises(RuntimeError):
        db.migrate(connection, tmp_path)
    assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    assert not connection.in_transaction


def test_una_migracion_en_python_sin_upgrade_se_rechaza(tmp_path):
    write(tmp_path, "001_sin.py", "X = 1\n")
    with pytest.raises(RuntimeError, match="upgrade"):
        db.migrate(db.connect(":memory:"), tmp_path)


def test_las_migraciones_sql_y_python_se_ordenan_por_numero(tmp_path):
    write(tmp_path, "001_a.sql", "CREATE TABLE t (n INTEGER);")
    write(tmp_path, "003_c.sql", "INSERT INTO t VALUES (3);")
    write(
        tmp_path, "002_b.py", "def upgrade(conn):\n    conn.execute('INSERT INTO t VALUES (2)')\n"
    )
    connection = db.connect(":memory:")
    assert db.migrate(connection, tmp_path) == [1, 2, 3]
    assert [r["n"] for r in connection.execute("SELECT n FROM t ORDER BY rowid")] == [2, 3]


# --- Autocontenida: solo la biblioteca estándar, nada del paquete `asistente` ---------------

MIGRATION = db.MIGRATIONS_DIR / "006_capitalizar_areas.py"


def imported_modules(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))  # importación relativa
    return found


PYTHON_MIGRATIONS = sorted(db.MIGRATIONS_DIR.glob("[0-9]*_*.py"))


@pytest.mark.parametrize("path", PYTHON_MIGRATIONS, ids=lambda path: path.name)
def test_ninguna_migracion_en_python_importa_nada_del_paquete_asistente(path):
    modules = imported_modules(path)
    assert not any(name == "asistente" or name.startswith(".") for name in modules), modules


@pytest.mark.parametrize("path", PYTHON_MIGRATIONS, ids=lambda path: path.name)
def test_ninguna_migracion_en_python_usa_mas_que_la_biblioteca_estandar(path):
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    assert imported_modules(path) <= allowed, imported_modules(path) - allowed


def test_hay_al_menos_una_migracion_en_python_vigilada():
    assert MIGRATION in PYTHON_MIGRATIONS


def test_el_detector_de_importaciones_ve_los_del_paquete(tmp_path):
    sample = tmp_path / "m.py"
    sample.write_text("import sqlite3\nfrom asistente.formato import cap_first\n", encoding="utf-8")
    assert imported_modules(sample) == {"sqlite3", "asistente"}
    sample.write_text("from . import algo\nfrom .. import otra\n", encoding="utf-8")
    assert imported_modules(sample) == {".", ".."}


def test_la_migracion_corre_en_un_interprete_aislado_sin_el_paquete(tmp_path):
    """Intérprete aparte (`-I`, otra carpeta): si importara `asistente`, fallaría."""
    connection = old_database(tmp_path)
    path = tmp_path / "datos.db"
    disk = sqlite3.connect(path)
    connection.backup(disk)
    disk.close()
    script = (
        "import importlib.util, sqlite3\n"
        f"spec = importlib.util.spec_from_file_location('m6', {str(MIGRATION)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        f"conn = sqlite3.connect({str(path)!r})\n"
        "conn.row_factory = sqlite3.Row\n"
        "module.upgrade(conn)\n"
        "conn.commit()\n"
        "print(','.join(r['name'] for r in conn.execute('SELECT name FROM areas ORDER BY id')))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Universidad,Proyectos,Iglesia,Personal"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("comprar", "Comprar"),
        ("álgebra", "Álgebra"),
        ("ñandú", "Ñandú"),
        ("ébano y marfil", "Ébano y marfil"),
        ("¿qué?", "¿Qué?"),
        ("¡hola!", "¡Hola!"),
        ("¿¡qué!?", "¿¡Qué!?"),
        ("iOS", "iOS"),
        ("eBay", "eBay"),
        ("iPhone", "iPhone"),
        ("UNAM", "UNAM"),
        ("Ya", "Ya"),
        ("123 a", "123 a"),
        ("ß", "ß"),
    ],
)
def test_la_regla_de_mayuscula_va_dentro_de_la_migracion(tmp_path, old, new):
    connection = old_database(tmp_path)
    added = add_area(connection, old)
    db.migrate(connection)
    assert names(connection)[added] == new


# --- Sobre una base con datos: atómica e idempotente --------------------------------------


def load_migration():
    spec = importlib.util.spec_from_file_location("migracion_006", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def populated(tmp_path: Path) -> sqlite3.Connection:
    """Áreas con y sin colisión, registro de clasificación con nombres, tareas, notas y avisos."""
    connection = old_database(tmp_path)
    ids = {
        name: add_area(connection, name)
        for name in ("viajes", "Musica", "música", "Salud", "álgebra", "iOS")
    }
    with connection:
        connection.executemany(
            "INSERT INTO classification_log (ts_utc, text_norm, source, pred_area, final_area)"
            " VALUES ('x', ?, 'user', ?, ?)",
            [
                ("uno", "personal", "personal"),
                ("dos", "universidad", None),
                ("tres", None, "viajes"),
                ("cuatro", "música", "música"),  # choca con "Musica": no se renombra
                ("cinco", "álgebra", "iOS"),
            ],
        )
        for number, area in enumerate((1, ids["viajes"], ids["Musica"], None), start=1):
            connection.execute(
                "INSERT INTO tasks (title, area_id, source_text, created_at, updated_at)"
                " VALUES (?, ?, ?, 'x', 'x')",
                (f"tarea {number}", area, f"tarea {number}"),
            )
        connection.execute(
            "INSERT INTO notes (text, area_id, created_at) VALUES ('nota', ?, 'x')",
            (ids["viajes"],),
        )
        connection.execute(
            "INSERT INTO reminders (text, fire_at_utc, area_id, created_at)"
            " VALUES ('aviso', '2026-10-05T00:00:00+00:00', ?, 'x')",
            (ids["álgebra"],),
        )
    return connection


def snapshot(connection) -> dict[str, list[tuple]]:
    tables = ("areas", "classification_log", "tasks", "notes", "reminders", "schema_migrations")
    return {
        table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
        for table in tables
    }


def test_sobre_una_base_con_datos_cambia_solo_lo_esperado(tmp_path):
    connection = populated(tmp_path)
    before = snapshot(connection)
    assert db.migrate(connection) == [6]
    after = snapshot(connection)
    assert [row[1] for row in after["areas"]] == [
        "Universidad",
        "Proyectos",
        "Iglesia",
        "Personal",
        "Viajes",
        "Musica",
        "música",
        "Salud",
        "Álgebra",
        "iOS",
    ]
    for table in ("tasks", "notes", "reminders"):  # siguen ligados por id: nada cambió
        assert after[table] == before[table]
    rows = connection.execute("SELECT text_norm, pred_area, final_area FROM classification_log")
    assert {row["text_norm"]: (row["pred_area"], row["final_area"]) for row in rows} == {
        "uno": ("Personal", "Personal"),
        "dos": ("Universidad", None),
        "tres": (None, "Viajes"),
        "cuatro": ("música", "música"),
        "cinco": ("Álgebra", "iOS"),
    }
    assert after["schema_migrations"][-1][0] == 6


def test_una_falla_a_mitad_no_deja_nada_a_medias(tmp_path):
    connection = populated(tmp_path)
    before = snapshot(connection)
    connection.executescript(
        """
        CREATE TRIGGER falla_a_mitad BEFORE UPDATE OF final_area ON classification_log
        WHEN NEW.final_area = 'Personal'
        BEGIN SELECT RAISE(ABORT, 'falla a mitad'); END;
        """
    )
    connection.commit()
    with pytest.raises(sqlite3.Error, match="falla a mitad"):
        db.migrate(connection)
    assert not connection.in_transaction
    assert snapshot(connection) == before  # ni las áreas ya renombradas, ni el registro, ni schema
    versions = [r["version"] for r in connection.execute("SELECT version FROM schema_migrations")]
    assert versions == [1, 2, 3, 4, 5]
    connection.execute("DROP TRIGGER falla_a_mitad")
    connection.commit()
    assert db.migrate(connection) == [6]  # sin el obstáculo se aplica completa
    assert names(connection)[4] == "Personal"


def test_ejecutarla_dos_veces_no_cambia_nada(tmp_path):
    connection = populated(tmp_path)
    db.migrate(connection)
    once = snapshot(connection)
    assert db.migrate(connection) == []  # el ejecutor no la repite
    load_migration().upgrade(connection)  # y aunque se llame a mano, no queda nada que cambiar
    connection.commit()
    assert snapshot(connection) == once


def test_ejecutarla_a_mano_dos_veces_sobre_la_base_vieja_es_idempotente(tmp_path):
    connection = populated(tmp_path)
    module = load_migration()
    module.upgrade(connection)
    first = snapshot(connection)
    module.upgrade(connection)
    assert snapshot(connection) == first
