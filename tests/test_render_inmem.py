"""Tests for in-memory rendering: render_text + render_bytes."""
import os
import pytest

import pyplantuml
from pyplantuml import (
    PlantUmlError, PlantUmlSyntaxError,
    render_text, render_bytes,
)

from .conftest import SIMPLE_PUML, CJK_PUML

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
INVALID_PUML = "@startuml\nA --bogus-> B\n@enduml"


def test_render_text_png_returns_png_bytes():
    out = render_text(SIMPLE_PUML, fmt="png")
    assert isinstance(out, bytes)
    assert out.startswith(PNG_HEADER)
    # PNG always ends with the IEND chunk (last 12 bytes are IEND + length 0 + CRC)
    assert b"IEND" in out[-16:]


def test_render_text_svg_starts_with_svg_root():
    out = render_text(SIMPLE_PUML, fmt="svg")
    assert b"<svg " in out[:200]
    assert b"</svg>" in out


def test_render_text_utxt_is_ascii_art():
    out = render_text(SIMPLE_PUML, fmt="utxt")
    # ASCII / UTXT output is plain text with box-drawing chars
    text = out.decode("utf-8")
    assert "┌" in text or "+" in text  # depending on plantuml version
    assert "Alice" in text or "A" in text  # the actor


def test_render_text_cjk_png_has_substantial_size():
    """CJK content should render visibly: PNG byte size scales with text width.
    Tofu glyphs (boxes) collapse the layout to <4KB; real glyphs >= 8KB."""
    out = render_text(CJK_PUML, fmt="png")
    assert out.startswith(PNG_HEADER)
    assert len(out) >= 4000, "CJK PNG suspiciously small (tofu?): {} bytes".format(len(out))


def test_render_text_extra_args_forwarded():
    """-SkinParam handwritten true changes look; just verify it doesn't error
    and that extra_args reach plantuml."""
    out = render_text(
        SIMPLE_PUML, fmt="png",
        extra_args=["-Sdefaultfontsize=10"],
    )
    assert out.startswith(PNG_HEADER)


def test_render_text_rejects_non_string():
    with pytest.raises(PlantUmlError, match="expects str"):
        render_text(b"@startuml\nA -> B\n@enduml")


def test_render_text_empty_source_raises():
    """Empty puml input → plantuml writes nothing to stdout → we raise."""
    with pytest.raises(PlantUmlError, match=r"produced no output"):
        render_text("")


def test_render_bytes_from_existing_file(tmp_path):
    p = tmp_path / "hello.puml"
    p.write_text(SIMPLE_PUML, encoding="utf-8")
    out = render_bytes(p, fmt="png")
    assert out.startswith(PNG_HEADER)


def test_render_bytes_from_existing_file_svg(tmp_path):
    p = tmp_path / "hello.puml"
    p.write_text(SIMPLE_PUML, encoding="utf-8")
    out = render_bytes(str(p), fmt="svg")
    assert b"<svg" in out[:200]


def test_render_bytes_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.puml"
    with pytest.raises(PlantUmlError, match="source not found"):
        render_bytes(missing)


def test_render_bytes_extra_args_forwarded(tmp_path):
    p = tmp_path / "hello.puml"
    p.write_text(SIMPLE_PUML, encoding="utf-8")
    out = render_bytes(p, extra_args=["-Sdefaultfontsize=12"])
    assert out.startswith(PNG_HEADER)


# --- strict-mode error feedback -----------------------------------------

def test_render_text_strict_valid_returns_bytes_unchanged():
    """strict=True doesn't touch the success path."""
    out = render_text(SIMPLE_PUML, strict=True)
    assert out.startswith(PNG_HEADER)


def test_render_text_lenient_bad_returns_error_image_bytes():
    """Default strict=False preserves the documented behaviour: bad
    puml yields the rendered error-image bytes (a real PNG whose
    visible content describes the problem)."""
    out = render_text(INVALID_PUML)  # strict=False is default
    assert out.startswith(PNG_HEADER)
    # Error image is meaningfully larger than a normal small render
    # because plantuml draws the error message text inside it.
    assert len(out) > 5000


def test_render_text_strict_bad_raises_with_structured_diagnostic():
    with pytest.raises(PlantUmlSyntaxError) as exc:
        render_text(INVALID_PUML, strict=True)
    e = exc.value
    # Structured fields from plantuml's -ttxt diagnostic block.
    assert e.line == 2
    assert e.column is not None
    assert "bogus" in e.snippet
    assert "Syntax Error" in e.description
    assert e.returncode is not None and e.returncode != 0
    # Full message is the verbatim diagnostic block.
    msg = str(e)
    assert "@startuml" in msg
    assert "^" in msg
    assert "Syntax Error" in msg


def test_render_text_strict_error_is_caught_by_plantumlerror():
    """PlantUmlSyntaxError subclasses PlantUmlError so legacy callers
    that `except PlantUmlError` still catch the strict-mode raise."""
    with pytest.raises(PlantUmlError):
        render_text(INVALID_PUML, strict=True)


def test_render_text_strict_svg_format_also_raises():
    """strict mode is fmt-agnostic — works on -tsvg too."""
    with pytest.raises(PlantUmlSyntaxError):
        render_text(INVALID_PUML, strict=True, fmt="svg")


def test_render_bytes_strict_bad_raises(tmp_path):
    p = tmp_path / "bad.puml"
    p.write_text(INVALID_PUML, encoding="utf-8")
    with pytest.raises(PlantUmlSyntaxError) as exc:
        render_bytes(p, strict=True)
    assert exc.value.line == 2


def test_render_bytes_strict_valid_returns_bytes(tmp_path):
    p = tmp_path / "good.puml"
    p.write_text(SIMPLE_PUML, encoding="utf-8")
    out = render_bytes(p, strict=True)
    assert out.startswith(PNG_HEADER)


def test_render_text_strict_fallback_when_ttxt_unparseable(monkeypatch):
    """Defensive path: render(strict=True) catches a non-zero rc but
    the follow-up -ttxt run produces text we can't parse.  The
    PlantUmlSyntaxError still raises with whatever raw text we got
    and the returncode preserved."""
    from pyplantuml import _diagnose as diag_mod

    monkeypatch.setattr(
        diag_mod, "_run_pipe_ttxt",
        lambda _src: "unrecognised format from upstream\n",
    )
    with pytest.raises(PlantUmlSyntaxError) as exc:
        render_text(INVALID_PUML, strict=True)
    e = exc.value
    assert "unrecognised format from upstream" in str(e)
    assert e.returncode is not None
    # Structured fields default to None when the parser bails.
    assert e.line is None
    assert e.column is None


def test_render_text_strict_fallback_with_empty_ttxt_output(monkeypatch):
    """If -ttxt returns nothing at all, raise with a synthesized
    placeholder message rather than ``str(e) == ""``."""
    from pyplantuml import _diagnose as diag_mod

    monkeypatch.setattr(diag_mod, "_run_pipe_ttxt", lambda _src: "")
    with pytest.raises(PlantUmlSyntaxError) as exc:
        render_text(INVALID_PUML, strict=True)
    assert "rc=" in str(exc.value)
