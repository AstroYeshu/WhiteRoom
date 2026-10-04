"""`scripts/backup_db.py`: respaldo con la API de `sqlite3`, 14 días de retención, código de salida.

Siempre con una base temporal; nunca con la base real ni con el `.env` del dueño.
"""

import importlib.util
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from asistente import db

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup_db.py"
TODAY = date(2026, 10, 4)


def load_script():
    spec = importlib.util.spec_from_file_location("backup_db", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return load_script()


@pytest.fixture
def source(tmp_path) -> Path:
    path = tmp_path / "data" / "asistente.db"
    conn = db.open_db(path)
    with conn:
        add_area(conn, "Salud")
    conn.close()
    return path


def add_area(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT INTO areas (name, description, created_at) VALUES (?, '', ?)",
        (name, "2026-10-04T00:00:00+00:00"),
    )


def backup_name(day: date) -> str:
    return f"asistente-{day.isoformat()}.db"


def area_names(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT name FROM areas ORDER BY name")]
    finally:
        conn.close()


def test_el_respaldo_tiene_la_fecha_y_el_mismo_contenido(script, source, tmp_path):
    target = tmp_path / "data" / "backups"
    result = script.backup(source, target, TODAY)
    assert result == target / backup_name(TODAY)
    assert "Salud" in area_names(result)
    assert area_names(result) == area_names(source)


def test_el_respaldo_incluye_lo_que_aun_esta_en_el_wal(script, source, tmp_path):
    """Una conexión abierta con datos confirmados (en el -wal) entra en el respaldo."""
    live = db.connect(source)
    with live:
        add_area(live, "Solo en el WAL")
    result = script.backup(source, tmp_path / "b", TODAY)
    live.close()
    assert "Solo en el WAL" in area_names(result)


def test_no_copia_lo_que_no_se_confirmo(script, source, tmp_path):
    live = db.connect(source)
    live.execute("BEGIN")
    add_area(live, "Sin confirmar")
    result = script.backup(source, tmp_path / "b", TODAY)
    live.rollback()
    live.close()
    assert "Sin confirmar" not in area_names(result)


def test_repetir_el_mismo_dia_reemplaza_el_respaldo(script, source, tmp_path):
    target = tmp_path / "b"
    script.backup(source, target, TODAY)
    conn = db.connect(source)
    with conn:
        add_area(conn, "Nueva")
    conn.close()
    result = script.backup(source, target, TODAY)
    assert "Nueva" in area_names(result)
    assert [p.name for p in target.iterdir()] == [backup_name(TODAY)]


def fill(target: Path, ages: list[int]) -> list[str]:
    target.mkdir(exist_ok=True)
    names = [backup_name(TODAY - timedelta(days=age)) for age in ages]
    for name in names:
        (target / name).write_bytes(b"x")
    return names


def test_conserva_14_dias_y_borra_los_mas_viejos(script, source, tmp_path):
    target = tmp_path / "b"
    fill(target, [1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 40])
    script.backup(source, target, TODAY)
    kept = sorted(p.name for p in target.iterdir())
    assert kept == sorted(
        backup_name(TODAY - timedelta(days=age)) for age in (0, 1, 2, 3, 4, 5, 6, 7, 13)
    )


def test_siempre_conserva_los_7_mas_recientes_aunque_sean_viejos(script, source, tmp_path):
    """Un mes sin respaldar: todos los anteriores pasan de 14 días, pero quedan 7 en total."""
    target = tmp_path / "b"
    fill(target, [20, 21, 22, 23, 24, 25, 26, 27, 28, 29])
    script.backup(source, target, TODAY)
    kept = sorted(p.name for p in target.iterdir())
    expected = [0, 20, 21, 22, 23, 24, 25]
    assert kept == sorted(backup_name(TODAY - timedelta(days=age)) for age in expected)


def test_con_pocos_respaldos_no_borra_ninguno_aunque_sean_viejos(script, source, tmp_path):
    target = tmp_path / "b"
    names = fill(target, [30, 60, 90])
    script.backup(source, target, TODAY)
    assert set(names) <= {p.name for p in target.iterdir()}


def test_nunca_borra_el_ultimo_aunque_su_fecha_este_vencida(script, source, tmp_path):
    """Con el reloj saltado 100 días al futuro, el respaldo nuevo es el último y se conserva."""
    target = tmp_path / "b"
    fill(target, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    future = TODAY + timedelta(days=100)
    result = script.backup(source, target, future)
    assert result.exists()
    assert len(list(target.iterdir())) == 7


def test_prune_nunca_deja_menos_de_7_ni_borra_el_mas_reciente(script, tmp_path):
    target = tmp_path / "b"
    fill(target, list(range(100, 120)))
    removed = script.prune(target, TODAY)
    left = sorted(p.name for p in target.iterdir())
    assert len(left) == 7
    assert backup_name(TODAY - timedelta(days=100)) in left  # el más reciente
    assert len(removed) == 13


def test_no_toca_archivos_que_no_son_respaldos(script, source, tmp_path):
    target = tmp_path / "b"
    target.mkdir()
    (target / "notas.txt").write_text("mío")
    (target / "asistente-2020-01-01.db.bak").write_text("mío")
    (target / "otra-2020-01-01.db").write_text("mío")
    script.backup(source, target, TODAY)
    assert (target / "notas.txt").exists()
    assert (target / "asistente-2020-01-01.db.bak").exists()
    assert (target / "otra-2020-01-01.db").exists()


def test_el_dia_de_retencion_es_exacto_con_un_reloj_inyectado(script, source, tmp_path):
    target = tmp_path / "b"
    old = TODAY - timedelta(days=14)
    fill(target, [1, 2, 3, 4, 5, 6, 7, 8])
    (target / backup_name(old)).write_bytes(b"x")
    script.backup(source, target, TODAY - timedelta(days=1))  # ayer: ese archivo tiene 13 días
    assert (target / backup_name(old)).exists()
    script.backup(source, target, TODAY)  # hoy: tiene 14 días
    assert not (target / backup_name(old)).exists()


def test_main_devuelve_0_si_sale_bien(script, source, tmp_path, capsys):
    code = script.main(["--db", str(source), "--dir", str(tmp_path / "b")], today=TODAY)
    assert code == 0
    assert backup_name(TODAY) in capsys.readouterr().out


def test_main_devuelve_distinto_de_0_si_la_base_no_existe_y_no_la_crea(script, tmp_path, capsys):
    missing = tmp_path / "nada" / "asistente.db"
    code = script.main(["--db", str(missing), "--dir", str(tmp_path / "b")], today=TODAY)
    assert code != 0
    assert not missing.exists()
    assert not list((tmp_path / "b").glob("*.db")) if (tmp_path / "b").exists() else True
    assert "no existe" in capsys.readouterr().err


def test_un_archivo_que_no_es_sqlite_falla_sin_pisar_el_respaldo_bueno(script, source, tmp_path):
    target = tmp_path / "b"
    good = script.backup(source, target, TODAY)
    good_bytes = good.read_bytes()
    broken = tmp_path / "roto.db"
    broken.write_bytes(b"esto no es sqlite" * 100)
    code = script.main(["--db", str(broken), "--dir", str(target)], today=TODAY)
    assert code != 0
    assert good.read_bytes() == good_bytes
    assert [p.name for p in target.iterdir()] == [backup_name(TODAY)]  # sin temporales


def test_si_el_respaldo_falla_no_se_borran_los_viejos(script, tmp_path):
    target = tmp_path / "b"
    target.mkdir()
    old = target / backup_name(TODAY - timedelta(days=30))
    old.write_bytes(b"x")
    code = script.main(["--db", str(tmp_path / "no.db"), "--dir", str(target)], today=TODAY)
    assert code != 0
    assert old.exists()


def test_por_defecto_guarda_en_backups_junto_a_la_base(script, source, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # sin .env aquí
    monkeypatch.setenv("DB_PATH", str(source))
    assert script.main([], today=TODAY) == 0
    assert (source.parent / "backups" / backup_name(TODAY)).exists()


def test_no_usa_el_binario_sqlite3():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in text and "os.system" not in text


def test_si_la_copia_no_esta_integra_falla_y_no_deja_nada(script, source, tmp_path, monkeypatch):
    monkeypatch.setattr(script, "_integrity_ok", lambda conn: False)
    target = tmp_path / "b"
    code = script.main(["--db", str(source), "--dir", str(target)], today=TODAY)
    assert code != 0
    assert list(target.iterdir()) == []


def test_la_verificacion_de_integridad_distingue_una_base_sana(script, source):
    conn = sqlite3.connect(source)
    try:
        assert script._integrity_ok(conn) is True
    finally:
        conn.close()


def test_la_verificacion_de_integridad_detecta_una_base_dañada(script, tmp_path):
    path = tmp_path / "dañada.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("CREATE INDEX t_v ON t (v)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"valor {n}" * 20,) for n in range(500)])
    conn.commit()
    conn.close()
    data = bytearray(path.read_bytes())
    for offset in range(len(data) // 2, len(data) // 2 + 4096, 7):
        data[offset] = 0xFF
    path.write_bytes(bytes(data))
    conn = sqlite3.connect(path)
    try:
        assert script._integrity_ok(conn) is False
    finally:
        conn.close()


def test_la_verificacion_de_integridad_no_revienta_con_basura(script, tmp_path):
    path = tmp_path / "basura.db"
    path.write_bytes(b"esto no es sqlite" * 100)
    conn = sqlite3.connect(path)
    try:
        assert script._integrity_ok(conn) is False
    finally:
        conn.close()


def test_si_la_copia_no_esta_integra_no_se_borra_nada_y_sale_con_error(
    script, source, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "b"
    names = fill(target, list(range(1, 30)))
    monkeypatch.setattr(script, "_integrity_ok", lambda conn: False)
    code = script.main(["--db", str(source), "--dir", str(target)], today=TODAY)
    assert code != 0
    assert sorted(p.name for p in target.iterdir()) == sorted(names)
    assert "FALLA" in capsys.readouterr().err


def test_si_la_base_no_existe_no_se_borra_nada_y_sale_con_error(script, tmp_path):
    target = tmp_path / "b"
    names = fill(target, list(range(1, 30)))
    code = script.main(["--db", str(tmp_path / "no.db"), "--dir", str(target)], today=TODAY)
    assert code != 0
    assert sorted(p.name for p in target.iterdir()) == sorted(names)


def test_si_no_se_puede_podar_el_respaldo_queda_pero_sale_con_error(
    script, source, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "b"
    fill(target, list(range(1, 30)))

    real_unlink = Path.unlink

    def deny(self, *args, **kwargs):
        if self.name.endswith(".tmp"):  # los temporales del propio respaldo sí se limpian
            return real_unlink(self, *args, **kwargs)
        raise PermissionError("sin permiso")

    monkeypatch.setattr(Path, "unlink", deny)
    code = script.main(["--db", str(source), "--dir", str(target)], today=TODAY)
    monkeypatch.undo()
    assert code != 0
    assert (target / backup_name(TODAY)).exists()
    assert "podar" in capsys.readouterr().err


def test_backup_directo_con_copia_danada_lanza_error_y_conserva_todo(
    script, source, tmp_path, monkeypatch
):
    target = tmp_path / "b"
    names = fill(target, list(range(1, 30)))
    monkeypatch.setattr(script, "_integrity_ok", lambda conn: False)
    with pytest.raises(script.BackupError):
        script.backup(source, target, TODAY)
    assert sorted(p.name for p in target.iterdir()) == sorted(names)


def test_backup_directo_si_falla_la_poda_lanza_backuperror_y_el_respaldo_queda(
    script, source, tmp_path, monkeypatch
):
    target = tmp_path / "b"
    fill(target, list(range(1, 30)))

    def fail(*args, **kwargs):
        raise PermissionError("sin permiso")

    monkeypatch.setattr(script, "prune", fail)
    with pytest.raises(script.BackupError, match="ya está hecho|está hecho"):
        script.backup(source, target, TODAY)
    assert (target / backup_name(TODAY)).exists()


def test_la_salida_sale_en_utf8_aunque_la_consola_sea_ascii(script, source, tmp_path, monkeypatch):
    import io
    import sys

    out, err = io.BytesIO(), io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(out, encoding="ascii", errors="strict"))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(err, encoding="ascii", errors="strict"))
    monkeypatch.setattr(script, "_integrity_ok", lambda conn: False)
    code = script.main(["--db", str(source), "--dir", str(tmp_path / "b")], today=TODAY)
    sys.stderr.flush()
    assert code == 1
    assert "no pasó la verificación".encode() in err.getvalue()  # tilde y ó en UTF-8


def test_el_exito_con_una_ruta_con_acentos_sale_en_utf8(script, source, tmp_path, monkeypatch):
    import io
    import sys

    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(out, encoding="ascii", errors="strict"))
    code = script.main(
        ["--db", str(source), "--dir", str(tmp_path / "respaldos ñandú")], today=TODAY
    )
    sys.stdout.flush()
    assert code == 0
    assert "ñandú".encode() in out.getvalue()
