"""External (subprocess-based) tests for the portable plantuml binary.

These run inside the same fresh distro container the selfcheck and
smoketest stages use.  python3 + pytest are the only things installed
beyond the binary itself; the binary's bundled JRE provides java.
"""
from .conftest import run_plantuml


def test_version_banner(plantuml):
    proc = run_plantuml(plantuml, "-version")
    text = (proc.stdout or "") + (proc.stderr or "")
    assert "PlantUML version" in text, text[:300]


def test_info_subcommand(plantuml):
    proc = run_plantuml(plantuml, "info")
    assert proc.returncode == 0, proc.stderr
    text = (proc.stdout or "") + (proc.stderr or "")
    assert "pyplantuml-bundled" in text or "PlantUML" in text, text[:300]


def test_help_works(plantuml):
    proc = run_plantuml(plantuml, "--help")
    text = (proc.stdout or "") + (proc.stderr or "")
    assert "Usage" in text or "plantuml" in text.lower(), text[:300]


def test_render_png(plantuml, simple_puml, tmp_path):
    proc = run_plantuml(plantuml, "-tpng", str(simple_puml), cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "simple.png"
    assert out.is_file()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert out.stat().st_size > 1000


def test_render_svg(plantuml, simple_puml, tmp_path):
    proc = run_plantuml(plantuml, "-tsvg", str(simple_puml), cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "simple.svg"
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "<svg " in text


def test_checkonly_valid(plantuml, simple_puml):
    proc = run_plantuml(plantuml, "-checkonly", str(simple_puml))
    assert proc.returncode == 0, proc.stderr


def test_checkonly_rejects_bad(plantuml, bad_puml):
    proc = run_plantuml(plantuml, "-checkonly", str(bad_puml))
    # plantuml exits non-zero on -checkonly when puml syntax is broken
    assert proc.returncode != 0, "expected non-zero exit on broken syntax"


def test_cjk_png_substantial(plantuml, cjk_puml, tmp_path):
    """CJK render must produce a real-glyph PNG, not tofu (square boxes).

    Tofu renders compress to <5 KB because every cell is identical;
    real anti-aliased glyphs blow that up to >=8 KB even on this
    small fixture.  4 KB is a conservative lower bound that still
    flags the tofu collapse.
    """
    proc = run_plantuml(plantuml, "-tpng", str(cjk_puml), cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "cjk.png"
    assert out.is_file()
    size = out.stat().st_size
    assert size >= 4000, "PNG suspiciously small ({} bytes — likely tofu)".format(size)


def test_cjk_svg_chinese_entity(plantuml, cjk_puml, tmp_path):
    proc = run_plantuml(plantuml, "-tsvg", str(cjk_puml), cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "cjk.svg"
    text = out.read_text(encoding="utf-8")
    # PlantUML emits CJK glyphs as numeric character entities;
    # "中" is U+4E2D = &#20013;
    assert "&#20013;" in text, "SVG missing Chinese character entity"
