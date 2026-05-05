"""
CJK rendering correctness — these tests are the ones that matter for the
"works on a slim container with no system fonts" guarantee.

Tofu (square-box) glyphs do not raise an error, so we cannot rely on the
return code.  Instead we use two complementary signals:

1. The PNG byte size: real anti-aliased CJK glyphs compress poorly; tofu
   compresses extremely well because every glyph cell is identical.  A
   render that contains the CJK_PUML fixture should comfortably exceed
   8 KB; a tofu render of the same fixture comes out closer to 2–3 KB.

2. The PNG dimensions: PlantUML lays out boxes/notes proportional to
   measured text width.  Tofu rendering produces ZERO advance for
   un-mapped glyphs which collapses widths and yields a much narrower
   image.  A real CJK render of CJK_PUML lands at >=500 px wide.
"""
from pathlib import Path

from pyplantuml import render

from .conftest import png_dimensions


def test_cjk_png_has_substantial_size(cjk_puml: Path, tmp_path: Path):
    render(cjk_puml, output_dir=tmp_path, fmt="png")
    out = tmp_path / "cjk.png"
    assert out.is_file()
    size = out.stat().st_size
    # Empirically the slim-container render lands at ~50 KB (50_549 bytes
    # observed across Python 3.7..3.14).  A tofu render is <5 KB.
    assert size >= 8_000, f"PNG suspiciously small ({size} bytes) — possible tofu"


def test_cjk_png_has_substantial_width(cjk_puml: Path, tmp_path: Path):
    render(cjk_puml, output_dir=tmp_path, fmt="png")
    out = tmp_path / "cjk.png"
    width, height = png_dimensions(out)
    assert width >= 400, f"PNG width {width}px too small — likely tofu collapse"
    assert height >= 400, f"PNG height {height}px too small"


def test_cjk_svg_has_all_three_languages(cjk_puml: Path, tmp_path: Path):
    render(cjk_puml, output_dir=tmp_path, fmt="svg")
    text = (tmp_path / "cjk.svg").read_text(encoding="utf-8")
    # 中 (Chinese) — must be present
    assert "&#20013;" in text
    # こ (Japanese hiragana ko) — U+3053
    assert "&#12371;" in text
    # 한 (Korean hangul) — U+D55C
    assert "&#54620;" in text
