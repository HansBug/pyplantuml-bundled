"""Tests for the warm-JVM Session class."""
import os
import time

import pytest

import pyplantuml
from pyplantuml import PlantUmlError, Session

from .conftest import SIMPLE_PUML

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def test_session_basic_with_statement_png():
    with Session(fmt="png") as s:
        out = s.render(SIMPLE_PUML)
    assert out.startswith(PNG_HEADER)


def test_session_renders_consecutive_diagrams_on_same_jvm():
    """The whole point of Session: one JVM, many renders."""
    with Session(fmt="png") as s:
        out1 = s.render(SIMPLE_PUML)
        pid_after_first = s._proc.pid
        out2 = s.render("@startuml\nC -> D : second\n@enduml")
        out3 = s.render("@startuml\nE -> F : third\n@enduml")
        pid_after_third = s._proc.pid
    assert pid_after_first == pid_after_third
    assert all(o.startswith(PNG_HEADER) for o in (out1, out2, out3))
    # Each render should produce different bytes (different content)
    assert out1 != out2
    assert out2 != out3


def test_session_svg_format():
    with Session(fmt="svg") as s:
        out = s.render(SIMPLE_PUML)
    assert b"<svg " in out[:200]
    assert b"</svg>" in out


def test_session_utxt_format():
    with Session(fmt="utxt") as s:
        out = s.render(SIMPLE_PUML)
    text = out.decode("utf-8")
    assert "┌" in text or "+" in text


def test_session_fmt_property():
    s = Session(fmt="svg")
    try:
        assert s.fmt == "svg"
    finally:
        s.close()


def test_session_closed_property_initially_false():
    s = Session(fmt="png")
    try:
        assert s.closed is False
    finally:
        s.close()
    assert s.closed is True


def test_session_render_after_close_raises():
    s = Session(fmt="png")
    s.close()
    with pytest.raises(PlantUmlError, match="Session is closed"):
        s.render(SIMPLE_PUML)


def test_session_close_is_idempotent():
    s = Session(fmt="png")
    s.close()
    # second close is a no-op, must not raise
    s.close()
    assert s.closed is True


def test_session_render_rejects_non_string():
    with Session(fmt="png") as s:
        with pytest.raises(PlantUmlError, match="expects str"):
            s.render(b"@startuml\nA -> B\n@enduml")


def test_session_bad_puml_returns_error_image_not_raise():
    """Plantuml renders an error PNG for syntactically broken puml; this is
    the documented behavior — Session.render returns those bytes without
    raising.  Use lint() if strict validation is needed."""
    with Session(fmt="png") as s:
        out = s.render("@startuml\nA --bogus-> B\n@enduml")
    assert out.startswith(PNG_HEADER)
    # The error PNG is meaningfully larger than a normal small diagram
    # because plantuml renders the error message text inside it.
    assert len(out) > 5000


def test_session_continues_after_bad_puml():
    """A bad puml in the middle of a session must not break following renders."""
    with Session(fmt="png") as s:
        good1 = s.render(SIMPLE_PUML)
        bad = s.render("@startuml\nA --bogus-> B\n@enduml")
        good2 = s.render("@startuml\nX -> Y\n@enduml")
    assert good1.startswith(PNG_HEADER)
    assert bad.startswith(PNG_HEADER)
    assert good2.startswith(PNG_HEADER)


def test_session_unicode_puml():
    """UTF-8 encoded puml with CJK content goes through the pipe correctly."""
    cjk = "@startuml\ntitle 测试\n甲 -> 乙 : 你好\n@enduml"
    with Session(fmt="png") as s:
        out = s.render(cjk)
    assert out.startswith(PNG_HEADER)
    assert len(out) >= 3000  # CJK with real glyphs renders to >3KB


def test_session_manual_close_without_with_statement():
    s = Session(fmt="png")
    out = s.render(SIMPLE_PUML)
    s.close()
    assert out.startswith(PNG_HEADER)
    assert s.closed


def test_session_jvm_args_forwarded():
    """Custom JVM args reach the JVM (verify the session still works with one)."""
    with Session(fmt="png", jvm_args=["-Xmx256m"]) as s:
        out = s.render(SIMPLE_PUML)
    assert out.startswith(PNG_HEADER)


def test_session_render_after_jvm_killed():
    """If the JVM dies between renders, the next render raises with diagnostics."""
    s = Session(fmt="png")
    try:
        s.render(SIMPLE_PUML)
        # Kill the JVM
        s._proc.kill()
        s._proc.wait(timeout=5)
        # Give the OS a moment for poll() to reflect the exit
        time.sleep(0.1)
        with pytest.raises(PlantUmlError) as exc:
            s.render(SIMPLE_PUML)
        assert "JVM" in str(exc.value)
    finally:
        s.close()


def test_session_render_after_stdin_closed():
    """If stdin is closed externally, render must raise PlantUmlError, not
    BrokenPipeError or OSError directly."""
    s = Session(fmt="png")
    try:
        s.render(SIMPLE_PUML)
        # Forcibly close stdin (simulating an external interruption)
        s._proc.stdin.close()
        time.sleep(0.1)
        with pytest.raises(PlantUmlError):
            s.render(SIMPLE_PUML)
    finally:
        s.close()
