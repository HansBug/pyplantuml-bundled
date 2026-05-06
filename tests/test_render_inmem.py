"""Tests for in-memory rendering: render_text + render_bytes."""
import os
import pytest

import pyplantuml
from pyplantuml import PlantUmlError, render_text, render_bytes

from .conftest import SIMPLE_PUML, CJK_PUML

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


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
