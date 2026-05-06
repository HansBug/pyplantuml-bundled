"""Tests for the warm-JVM Session class."""
import os
import time

import pytest

import pyplantuml
from pyplantuml import PlantUmlError, Session
from pyplantuml.session import _read_until_delim_terminated

from .conftest import SIMPLE_PUML

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
DELIM = b"__TEST_DELIM__"


def _chunked_reader(chunks):
    """Build a read_fn that yields ``chunks`` in order, then b'' (EOF)."""
    iterator = iter(chunks)

    def read_fn(_size):
        try:
            return next(iterator)
        except StopIteration:
            return b""

    return read_fn


def _no_stderr():
    return ""


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
    # Diagnostic-rich asserts so a CI failure surfaces which output is
    # malformed and what it starts with.
    assert out1.startswith(PNG_HEADER), (
        "out1 missing PNG header: len=%d, head=%s, tail=%s"
        % (len(out1), out1[:32].hex(), out1[-16:].hex())
    )
    assert out2.startswith(PNG_HEADER), (
        "out2 missing PNG header: len=%d, head=%s, tail=%s"
        % (len(out2), out2[:32].hex(), out2[-16:].hex())
    )
    assert out3.startswith(PNG_HEADER), (
        "out3 missing PNG header: len=%d, head=%s, tail=%s"
        % (len(out3), out3[:32].hex(), out3[-16:].hex())
    )
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
    assert good1.startswith(PNG_HEADER), (
        "good1 head=%s len=%d" % (good1[:32].hex(), len(good1))
    )
    assert bad.startswith(PNG_HEADER), (
        "bad head=%s len=%d" % (bad[:32].hex(), len(bad))
    )
    assert good2.startswith(PNG_HEADER), (
        "good2 head=%s len=%d" % (good2[:32].hex(), len(good2))
    )


def test_session_unicode_puml():
    """UTF-8 encoded puml with CJK content goes through the pipe correctly."""
    cjk = "@startuml\ntitle 测试\n甲 -> 乙 : 你好\n@enduml"
    with Session(fmt="png") as s:
        out = s.render(cjk)
    assert out.startswith(PNG_HEADER)
    # PlantUML's PNG byte size for the same input has shifted across
    # versions (1.2024.7 → ~1850B, 1.2026.2 → ~1700B as the renderer
    # tightened compression / default skin params).  Floor of 1500B
    # comfortably distinguishes "real glyphs rendered" from the tofu
    # case where every character collapses to an identical empty box
    # (highly compressible, ~700-900B).
    assert len(out) >= 1500


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


# --- _read_until_delim_terminated framing branches ----------------------
# These exercise the post-DELIM line-terminator handling without spawning
# a JVM — the framing logic was extracted to a plain function precisely
# so each branch (LF, CRLF, split flushes, EOF, defensive fallback) gets
# direct coverage on every CI runner regardless of platform.


def test_read_frame_basic_lf_in_one_chunk():
    image = b"IMG-CONTENTS"
    result = _read_until_delim_terminated(
        _chunked_reader([image + DELIM + b"\n"]), DELIM, _no_stderr
    )
    assert result == image


def test_read_frame_split_image_then_delim_lf():
    image = b"IMG-PART-1-IMG-PART-2"
    result = _read_until_delim_terminated(
        _chunked_reader([image[:8], image[8:] + DELIM + b"\n"]),
        DELIM, _no_stderr,
    )
    assert result == image


def test_read_frame_delim_arrives_without_lf_then_lf_arrives():
    image = b"IMG"
    # Reader serves DELIM with no terminator yet, then LF in next read.
    result = _read_until_delim_terminated(
        _chunked_reader([image + DELIM, b"\n"]), DELIM, _no_stderr,
    )
    assert result == image


def test_read_frame_crlf_in_one_chunk():
    image = b"IMG-CRLF"
    result = _read_until_delim_terminated(
        _chunked_reader([image + DELIM + b"\r\n"]), DELIM, _no_stderr,
    )
    assert result == image


def test_read_frame_split_cr_then_lf():
    image = b"IMG-CR-LF"
    # CR arrives in one read, LF in the next — exercises the CR-pending
    # `continue` branch.
    result = _read_until_delim_terminated(
        _chunked_reader([image + DELIM + b"\r", b"\n"]), DELIM, _no_stderr,
    )
    assert result == image


def test_read_frame_eof_before_delim_raises():
    with pytest.raises(PlantUmlError, match="JVM closed stdout"):
        _read_until_delim_terminated(
            _chunked_reader([b"PARTIAL"]),  # then EOF
            DELIM, _no_stderr,
        )


def test_read_frame_eof_immediately_raises():
    with pytest.raises(PlantUmlError, match="JVM closed stdout"):
        _read_until_delim_terminated(
            _chunked_reader([]),  # immediate EOF
            DELIM, _no_stderr,
        )


def test_read_frame_eof_includes_stderr_excerpt():
    def stderr_fn():
        return "Some real failure message"
    with pytest.raises(PlantUmlError, match="Some real failure message"):
        _read_until_delim_terminated(
            _chunked_reader([]), DELIM, stderr_fn,
        )


def test_read_frame_eof_with_empty_stderr_uses_placeholder():
    with pytest.raises(PlantUmlError, match=r"\(empty\)"):
        _read_until_delim_terminated(
            _chunked_reader([]), DELIM, _no_stderr,
        )


def test_read_frame_delim_followed_by_garbage_returns_image_defensively():
    """Defensive fallback: if DELIM is followed by something that is
    neither CR nor LF (shouldn't happen with -pipedelimitor but
    can't be ruled out across plantuml versions), return the image
    rather than hanging."""
    image = b"IMG"
    result = _read_until_delim_terminated(
        _chunked_reader([image + DELIM + b"X"]), DELIM, _no_stderr,
    )
    assert result == image


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
