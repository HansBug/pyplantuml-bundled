"""End-to-end tests using the public Python API."""
import os
from pathlib import Path

import pytest

import pyplantuml
from pyplantuml import PlantUmlError, check, render, run, version


def test_jar_and_jre_present():
    assert pyplantuml.JAR_PATH.exists(), pyplantuml.JAR_PATH
    assert pyplantuml.JAVA_BIN.exists(), pyplantuml.JAVA_BIN


def test_version_reports_plantuml_and_jre():
    out = version()
    assert "PlantUML version" in out, out
    assert "OpenJDK" in out, out


def test_render_png(simple_puml: Path, tmp_path: Path):
    render(simple_puml, output_dir=tmp_path, fmt="png")
    out = tmp_path / "simple.png"
    assert out.is_file()
    head = out.read_bytes()[:8]
    assert head == b"\x89PNG\r\n\x1a\n"
    assert out.stat().st_size > 1000


def test_render_svg_has_chinese_entity(cjk_puml: Path, tmp_path: Path):
    render(cjk_puml, output_dir=tmp_path, fmt="svg")
    out = tmp_path / "cjk.svg"
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "<svg " in text
    # PlantUML's SVG encoding of CJK has shifted across versions:
    # 1.2020-1.2022 emit literal UTF-8 ("中"), 1.2024+ emit numeric
    # character entities ("&#20013;").  Both are valid renderings of
    # U+4E2D — the test only fails when the character is absent in
    # any form (which would mean the diagram silently dropped CJK).
    assert ("中" in text) or ("&#20013;" in text), (
        "SVG seems to be missing the Chinese character 中"
    )


def test_checkonly_valid(simple_puml: Path):
    assert check(simple_puml) is True


def test_checkonly_rejects_bad(bad_puml: Path):
    assert check(bad_puml) is False


def test_run_passthrough_help():
    proc = run(["-help"], capture_output=True, check=False)
    out = (proc.stdout or "") + (proc.stderr or "")
    # plantuml.jar -help prints a usage banner regardless of return code
    assert "Usage" in out or "Plantuml" in out or "plantuml" in out, out[:400]


def test_render_missing_source_raises(tmp_path: Path):
    with pytest.raises(PlantUmlError):
        render(tmp_path / "does-not-exist.puml")


def test_pyplantuml_java_override(simple_puml: Path, tmp_path: Path, monkeypatch):
    """If PYPLANTUML_JAVA points to a missing path we get a clear error."""
    monkeypatch.setenv("PYPLANTUML_JAVA", str(tmp_path / "no-such-java"))
    with pytest.raises(PlantUmlError):
        render(simple_puml, output_dir=tmp_path)
