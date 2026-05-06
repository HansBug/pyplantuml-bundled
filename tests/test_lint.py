"""Tests for lint() / lint_text() and the Diagnostic dataclass-like."""
import pytest

import pyplantuml
from pyplantuml import Diagnostic, PlantUmlError, lint, lint_text
from pyplantuml._diagnose import _parse_diagnostics, _strip_known_noise


# --- Diagnostic class behavior -------------------------------------------

def test_diagnostic_repr_includes_all_fields():
    d = Diagnostic(level="error", line=12, column=3, message="oops", snippet="A -> B")
    r = repr(d)
    assert r.startswith("Diagnostic(")
    assert "level='error'" in r
    assert "line=12" in r
    assert "column=3" in r
    assert "message='oops'" in r
    assert "snippet='A -> B'" in r


def test_diagnostic_equality_by_value():
    a = Diagnostic("error", 1, 2, "x", "y")
    b = Diagnostic("error", 1, 2, "x", "y")
    assert a == b
    assert hash(a) == hash(b)


def test_diagnostic_inequality_when_field_differs():
    a = Diagnostic("error", 1, 2, "x", "y")
    b = Diagnostic("error", 1, 2, "x", "z")  # snippet differs
    assert a != b


def test_diagnostic_inequality_with_other_type():
    d = Diagnostic("error", 1, 2, "x", "y")
    assert d != ("error", 1, 2, "x", "y")
    assert d != "Diagnostic(level='error', ...)"


def test_diagnostic_default_args():
    d = Diagnostic(level="error")
    assert d.line is None
    assert d.column is None
    assert d.message == ""
    assert d.snippet is None


def test_diagnostic_hash_with_unhashable_field_falls_back_to_id():
    # message is a list (unhashable) → __hash__ falls back to id(self)
    d = Diagnostic("error", None, None, ["multi"], None)
    h = hash(d)
    assert h == id(d)


# --- _strip_known_noise --------------------------------------------------

def test_strip_known_noise_filters_fontconfig():
    raw = (
        'Fontconfig warning: "/usr/share/fontconfig/conf.avail/05-reset-dirs-sample.conf", '
        'line 6: unknown element "reset-dirs"\n'
        "Some diagram description contains errors\n"
    )
    cleaned = _strip_known_noise(raw)
    assert "Fontconfig" not in cleaned
    assert cleaned == "Some diagram description contains errors"


def test_strip_known_noise_filters_jvm_warnings():
    raw = (
        "WARNING: An illegal reflective access operation has occurred\n"
        "WARNING: Use --illegal-access=warn to enable warnings\n"
        "Some diagram description contains errors\n"
    )
    cleaned = _strip_known_noise(raw)
    assert "WARNING" not in cleaned
    assert "Please consider reporting" not in cleaned
    assert cleaned == "Some diagram description contains errors"


def test_strip_known_noise_keeps_unknown_lines():
    raw = "Some random plantuml message\nAnother detail"
    cleaned = _strip_known_noise(raw)
    assert cleaned == "Some random plantuml message\nAnother detail"


def test_strip_known_noise_drops_blank_lines():
    raw = "  \n\nSome real message\n  \n"
    cleaned = _strip_known_noise(raw)
    assert cleaned == "Some real message"


def test_strip_known_noise_filters_all_extra_jvm_prefixes():
    """Coverage for every drop_prefixes entry."""
    raw = (
        "Fontconfig error: bad config\n"
        "WARNING: Please consider reporting this to the developers\n"
        "WARNING: All illegal access operations will be denied\n"
        "the actual problem"
    )
    cleaned = _strip_known_noise(raw)
    assert "Fontconfig" not in cleaned
    assert "WARNING" not in cleaned
    assert cleaned == "the actual problem"


# --- _parse_diagnostics --------------------------------------------------

def test_parse_diagnostics_rc_zero_returns_empty():
    assert _parse_diagnostics(0, "") == []
    # Even with stderr noise, rc=0 means valid
    assert _parse_diagnostics(0, "Fontconfig warning: foo") == []


def test_parse_diagnostics_rc_nonzero_returns_one_diag():
    diags = _parse_diagnostics(200, "Some diagram description contains errors\n")
    assert len(diags) == 1
    assert diags[0].level == "error"
    assert diags[0].line is None
    assert diags[0].column is None
    assert diags[0].message == "Some diagram description contains errors"
    assert diags[0].snippet is None


def test_parse_diagnostics_rc_nonzero_empty_stderr_synthesizes_message():
    diags = _parse_diagnostics(99, "")
    assert len(diags) == 1
    assert "code 99" in diags[0].message


def test_parse_diagnostics_filters_noise_from_message():
    raw = "Fontconfig warning: foo\nSome diagram description contains errors\n"
    diags = _parse_diagnostics(200, raw)
    assert diags[0].message == "Some diagram description contains errors"


def test_parse_diagnostics_only_noise_synthesizes_message():
    """If filtering noise leaves nothing, fall back to a synthetic message."""
    raw = "Fontconfig warning: foo\nWARNING: An illegal reflective access\n"
    diags = _parse_diagnostics(200, raw)
    assert "code 200" in diags[0].message


# --- lint() against real .puml files ------------------------------------

VALID_PUML = "@startuml\nA -> B : hi\n@enduml\n"
INVALID_PUML = "@startuml\nA --bogus-> B\n@enduml\n"


def test_lint_valid_file_returns_empty(tmp_path):
    p = tmp_path / "good.puml"
    p.write_text(VALID_PUML, encoding="utf-8")
    assert lint(p) == []


def test_lint_invalid_file_returns_one_diagnostic(tmp_path):
    p = tmp_path / "bad.puml"
    p.write_text(INVALID_PUML, encoding="utf-8")
    diags = lint(p)
    assert len(diags) == 1
    assert diags[0].level == "error"
    # The plantuml stderr message is well-known
    assert "errors" in diags[0].message.lower()


def test_lint_accepts_str_path(tmp_path):
    p = tmp_path / "good.puml"
    p.write_text(VALID_PUML, encoding="utf-8")
    assert lint(str(p)) == []


def test_lint_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.puml"
    with pytest.raises(PlantUmlError, match="source not found"):
        lint(missing)


# --- lint_text() ---------------------------------------------------------

def test_lint_text_valid_returns_empty():
    assert lint_text(VALID_PUML) == []


def test_lint_text_invalid_returns_diagnostic():
    diags = lint_text(INVALID_PUML)
    assert len(diags) == 1
    assert diags[0].level == "error"


def test_lint_text_rejects_non_string():
    with pytest.raises(PlantUmlError, match="expects str"):
        lint_text(b"@startuml\nA -> B\n@enduml")


def test_lint_text_with_unicode_content():
    """CJK content is valid puml; lint_text shouldn't complain about
    encoding or anything."""
    src = "@startuml\ntitle 测试\n甲 -> 乙 : 你好\n@enduml"
    assert lint_text(src) == []
