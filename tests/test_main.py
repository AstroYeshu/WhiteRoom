import io
import sys

from asistente import main as app


def test_dry_run_arranca_sin_secretos_y_responde(monkeypatch, tmp_path, capsys):
    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "ASSISTANT_ANTHROPIC_KEY", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # la base del dry-run se crea aquí, no en el proyecto
    monkeypatch.setattr(sys, "stdin", io.StringIO("/start\n/ayuda\nhola\n/salir\n"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    assert app.main(["--dry-run"]) == 0

    sys.stdout.seek(0)
    output = sys.stdout.read()
    assert "Hola" in output
    assert "Ayuda" in output and "Consultar" in output  # /ayuda, agrupada por tipo
    assert "¿Qué es?\n\nHola" in output  # el mensaje libre abre la tarjeta de la bandeja
    assert "¿Qué es?" in output
    assert (tmp_path / "data" / "dry_run.db").exists()


def test_modo_real_sin_config_falla_con_codigo_2(monkeypatch, tmp_path, capsys):
    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "TZ_NAME", "CURRENCY_CODE", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # sin .env aquí

    assert app.main([]) == 2
    assert "Faltan variables obligatorias" in capsys.readouterr().err


def test_dry_run_atiende_una_pulsacion_de_boton(monkeypatch, tmp_path, caplog):
    """El cableado de `main` debe servir también a los botones (`handle_choice`), no solo a los
    mensajes: escribir el número de un botón de la consola es una pulsación."""
    for name in ("TELEGRAM_BOT_TOKEN", "ALLOWED_USER_ID", "DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("hola\n1\n/salir\n"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    assert app.main(["--dry-run"]) == 0

    sys.stdout.seek(0)
    output = sys.stdout.read()
    assert (
        "¿En qué área va?" in output or "Tarea guardada" in output
    )  # el botón 1 avanzó la tarjeta
    assert "Error" not in output
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
