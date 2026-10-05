"""`scripts/eval_classifier.py`: lee las etiquetas del dueño con UNA fila por captura.

Hoy no compara clasificadores (no los hay: Fase 2); resume lo que el dueño decidió.
"""

import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from asistente import db
from asistente.core import classification, tasks

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eval_classifier.py"


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("eval_classifier", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def label(conn, clock, kind, area, corrected, capture=True, text="x"):
    task_id = tasks.create_task(conn, text, clock).id if capture else None
    classification.log_user_decision(conn, clock, text, kind, area, corrected, task_id)
    return task_id


def test_una_fila_por_captura_aunque_se_haya_cambiado(script, conn, clock):
    task_id = label(conn, clock, "reminder", "personal", False)
    classification.log_user_decision(conn, clock, "x", "task", "personal", False, task_id)
    labels = script.load_labels(conn)
    assert len(labels) == 1
    assert (labels[0].final_kind, labels[0].user_corrected) == ("task", True)


def test_las_filas_sin_captura_cuentan_cada_una(script, conn, clock):
    label(conn, clock, "task", None, False, capture=False)
    label(conn, clock, "task", None, False, capture=False)
    label(conn, clock, "note", None, False)
    assert len(script.load_labels(conn)) == 3


def test_solo_cuenta_las_etiquetas_del_dueno(script, conn, clock):
    label(conn, clock, "task", None, False)
    conn.execute(
        "INSERT INTO classification_log (ts_utc, text_norm, source, final_kind)"
        " VALUES ('x', 'x', 'jev', 'note')"
    )
    assert [item.final_kind for item in script.load_labels(conn)] == ["task"]


def test_el_resumen_cuenta_por_tipo_area_y_correcciones(script, conn, clock):
    label(conn, clock, "task", "personal", False)
    label(conn, clock, "task", None, True)
    label(conn, clock, "reminder", "iglesia", False)
    summary = script.summarize(script.load_labels(conn))
    assert summary.total == 3
    assert summary.by_kind == {"task": 2, "reminder": 1}
    assert summary.by_area == {"personal": 1, "(sin área)": 1, "iglesia": 1}
    assert summary.corrected == 1


def test_el_resumen_vacio_no_divide_por_cero(script, conn):
    summary = script.summarize(script.load_labels(conn))
    assert summary.total == 0 and summary.corrected == 0
    assert "0" in script.render(summary)


def test_main_imprime_el_resumen_y_no_toca_la_base(script, tmp_path, capsys):
    path = tmp_path / "data" / "asistente.db"
    conn = db.open_db(path)

    def clock():
        return datetime.now(UTC)

    label(conn, clock, "task", None, False)
    conn.close()
    before = path.read_bytes()
    assert script.main(["--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "1" in out and "task" in out
    assert path.read_bytes() == before


def test_main_sin_base_sale_con_error_y_no_la_crea(script, tmp_path, capsys):
    missing = tmp_path / "nada.db"
    assert script.main(["--db", str(missing)]) != 0
    assert not missing.exists()
    assert "FALLA" in capsys.readouterr().err


def test_la_base_se_abre_en_solo_lectura(script, tmp_path):
    path = tmp_path / "asistente.db"
    db.open_db(path).close()
    conn = script.open_readonly(path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM classification_log")
    conn.close()


def test_main_sin_base_dice_que_no_existe(script, tmp_path, capsys):
    script.main(["--db", str(tmp_path / "nada.db")])
    assert "no existe" in capsys.readouterr().err


def make_db(tmp_path):
    path = tmp_path / "asistente.db"
    conn = db.open_db(path)

    def clock():
        return datetime.now(UTC)

    label(conn, clock, "task", None, True)
    label(conn, clock, "reminder", "iglesia", False)
    conn.execute(
        "INSERT INTO classification_log (ts_utc, text_norm, source, final_kind)"
        " VALUES ('x', 'x', 'jev', 'note')"
    )
    conn.commit()
    conn.close()
    return path


def test_main_cuenta_solo_las_etiquetas_del_dueno(script, tmp_path, capsys):
    script.main(["--db", str(make_db(tmp_path))])
    out = capsys.readouterr().out
    assert "Capturas etiquetadas: 2" in out and "note" not in out


def test_main_informa_las_corregidas(script, tmp_path, capsys):
    script.main(["--db", str(make_db(tmp_path))])
    assert "Corregidas por el dueño: 1" in capsys.readouterr().out


def test_main_nombra_lo_que_no_tiene_area(script, tmp_path, capsys):
    script.main(["--db", str(make_db(tmp_path))])
    assert "(sin área): 1" in capsys.readouterr().out


def test_abrir_en_solo_lectura_una_base_que_no_existe_falla_y_no_la_crea(script, tmp_path):
    missing = tmp_path / "nada.db"
    with pytest.raises(sqlite3.OperationalError):
        script.open_readonly(missing)
    assert not missing.exists()


def test_main_sin_base_no_confunde_con_un_error_de_lectura(script, tmp_path, capsys):
    script.main(["--db", str(tmp_path / "nada.db")])
    assert "no se pudo leer" not in capsys.readouterr().err
