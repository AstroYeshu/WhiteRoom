"""Migración 006: pone en mayúscula la primera letra de las áreas existentes (sin pisar ninguna).

Es la primera migración en Python (`006_capitalizar_areas.py`): el ejecutor de `db.py` acepta
`NNN_nombre.py` con una función `upgrade(conn)`, dentro de la misma transacción que las `.sql`.
En SQL no se puede: `upper()` de SQLite solo conoce ASCII y no hay forma de comparar sin acentos.
"""

import shutil
import sqlite3
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
