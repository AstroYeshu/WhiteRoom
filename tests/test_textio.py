"""`force_utf8_output`: stdout y stderr salen en UTF-8 aunque la consola no lo sea."""

import io
import sys

from asistente.textio import force_utf8_output


def ascii_stream() -> tuple[io.BytesIO, io.TextIOWrapper]:
    raw = io.BytesIO()
    return raw, io.TextIOWrapper(raw, encoding="ascii", errors="strict")


def test_stdout_pasa_a_utf8(monkeypatch):
    raw, stream = ascii_stream()
    monkeypatch.setattr(sys, "stdout", stream)
    force_utf8_output()
    print("canción ñ")
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8") == "canción ñ\n"


def test_stderr_pasa_a_utf8(monkeypatch):
    raw, stream = ascii_stream()
    monkeypatch.setattr(sys, "stderr", stream)
    force_utf8_output()
    print("verificación", file=sys.stderr)
    sys.stderr.flush()
    assert raw.getvalue().decode("utf-8") == "verificación\n"


def test_un_flujo_sin_reconfigure_no_rompe(monkeypatch):
    class Plain:
        def write(self, text):
            return len(text)

    monkeypatch.setattr(sys, "stdout", Plain())
    monkeypatch.setattr(sys, "stderr", Plain())
    force_utf8_output()
