"""Tests for lint() / lint_text() / Diagnostic / PlantUmlSyntaxError
and the underlying ``-ttxt`` diagnostic parser."""
import pytest

import pyplantuml
from pyplantuml import (
    Diagnostic,
    PlantUmlError,
    PlantUmlSyntaxError,
    lint,
    lint_text,
)
from pyplantuml._diagnose import _parse_ttxt_diagnostic, _run_pipe_ttxt


VALID_PUML = "@startuml\nA -> B : hi\n@enduml\n"
INVALID_PUML = "@startuml\nA --bogus-> B\n@enduml\n"


# --- Diagnostic class behavior -------------------------------------------

def test_diagnostic_repr_includes_all_fields():
    d = Diagnostic(
        level="error", line=12, column=3, message="oops",
        snippet="A -> B", description="Syntax Error?",
    )
    r = repr(d)
    assert r.startswith("Diagnostic(")
    assert "level='error'" in r
    assert "line=12" in r
    assert "column=3" in r
    assert "message='oops'" in r
    assert "snippet='A -> B'" in r
    assert "description='Syntax Error?'" in r


def test_diagnostic_equality_by_value():
    a = Diagnostic("error", 1, 2, "x", "y", "z")
    b = Diagnostic("error", 1, 2, "x", "y", "z")
    assert a == b
    assert hash(a) == hash(b)


def test_diagnostic_inequality_when_field_differs():
    a = Diagnostic("error", 1, 2, "x", "y", "z")
    b = Diagnostic("error", 1, 2, "x", "y", "DIFFERENT")
    assert a != b


def test_diagnostic_inequality_with_other_type():
    d = Diagnostic("error", 1, 2, "x", "y", "z")
    assert d != ("error", 1, 2, "x", "y", "z")


def test_diagnostic_default_args():
    d = Diagnostic(level="error")
    assert d.line is None
    assert d.column is None
    assert d.message == ""
    assert d.snippet is None
    assert d.description is None


def test_diagnostic_hash_with_unhashable_field_falls_back_to_id():
    d = Diagnostic("error", None, None, ["unhashable"], None, None)
    h = hash(d)
    assert h == id(d)


# --- PlantUmlSyntaxError -------------------------------------------------

def test_syntax_error_is_subclass_of_plantuml_error():
    """`except PlantUmlError` keeps catching the new strict error."""
    assert issubclass(PlantUmlSyntaxError, PlantUmlError)


def test_syntax_error_constructor_fields():
    e = PlantUmlSyntaxError(
        "diagnostic", line=5, column=2,
        snippet="bad line", description="Syntax Error?",
        returncode=200,
    )
    assert str(e) == "diagnostic"
    assert e.line == 5
    assert e.column == 2
    assert e.snippet == "bad line"
    assert e.description == "Syntax Error?"
    assert e.returncode == 200


def test_syntax_error_default_fields():
    e = PlantUmlSyntaxError("just a message")
    assert e.line is None
    assert e.column is None
    assert e.snippet is None
    assert e.description is None
    assert e.returncode is None


# --- _parse_ttxt_diagnostic (parser) -------------------------------------

def test_parse_ttxt_returns_none_for_valid_diagram_output():
    """ASCII-art rendered diagram is NOT an error block."""
    valid_ascii_art = (
        "     ┌─┐          ┌─┐\n"
        "     │A│          │B│\n"
        "     └┬┘          └┬┘\n"
        "      │    hi      │\n"
        "      │───────────>│\n"
    )
    assert _parse_ttxt_diagnostic(valid_ascii_art) is None


def test_parse_ttxt_returns_none_for_empty_input():
    assert _parse_ttxt_diagnostic("") is None
    assert _parse_ttxt_diagnostic(None) is None


def test_parse_ttxt_extracts_line_column_snippet_description():
    # Verbatim 1.2024.7-style diagnostic block.
    block = (
        "[From string (line 2) ]\n"
        "                       \n"
        "@startuml              \n"
        "A --bogus-> B          \n"
        "^^^^^                  \n"
        " Syntax Error?         \n"
    )
    info = _parse_ttxt_diagnostic(block)
    assert info is not None
    assert info["line"] == 2
    assert info["column"] == 1  # carets start at col 1
    assert info["snippet"] == "A --bogus-> B"
    assert info["description"] == "Syntax Error?"
    # raw is the (right-stripped) reconstruction
    assert "@startuml" in info["raw"]
    assert "^^^^^" in info["raw"]


def test_parse_ttxt_handles_indented_carets():
    """Plantuml sometimes flags a token that's not at the start of the
    line — the caret line then has leading spaces.  Column should
    reflect that."""
    block = (
        "[From string (line 3) ]\n"
        "\n"
        "@startuml\n"
        "title hello\n"
        "    nonsense_thing here\n"
        "    ^^^^^\n"
        " Some Other Error\n"
    )
    info = _parse_ttxt_diagnostic(block)
    assert info is not None
    assert info["line"] == 3
    assert info["column"] == 5  # 4 leading spaces → col 5 (1-based)
    assert info["snippet"] == "    nonsense_thing here"
    assert info["description"] == "Some Other Error"


def test_parse_ttxt_handles_newer_description_with_extra_context():
    """1.2026+ appends ' (Assumed diagram type: sequence)' — preserve
    it verbatim in description rather than dropping the parenthetical."""
    block = (
        "[From string (line 2) ]\n"
        "\n"
        "@startuml\n"
        "A --bogus-> B\n"
        "^^^^^\n"
        " Syntax Error? (Assumed diagram type: sequence)\n"
    )
    info = _parse_ttxt_diagnostic(block)
    assert info["description"] == (
        "Syntax Error? (Assumed diagram type: sequence)"
    )


def test_parse_ttxt_returns_none_when_no_header_marker():
    """Defensive: if the text lacks the [From ...] header, treat as
    non-error so we don't false-positive."""
    text = "this is not an error block\n^^^^^ this caret is bait\n"
    assert _parse_ttxt_diagnostic(text) is None


def test_parse_ttxt_handles_missing_caret_gracefully():
    """If plantuml ever emits a header without a caret line (unusual
    but possible), still return a dict — line is set, column/snippet/
    description default to None."""
    block = (
        "[From string (line 4) ]\n"
        "Some plantuml message about something but no caret\n"
    )
    info = _parse_ttxt_diagnostic(block)
    assert info is not None
    assert info["line"] == 4
    assert info["column"] is None
    assert info["snippet"] is None
    assert info["description"] is None


# --- lint() against real .puml files ------------------------------------

def test_lint_valid_file_returns_empty(tmp_path):
    p = tmp_path / "good.puml"
    p.write_text(VALID_PUML, encoding="utf-8")
    assert lint(p) == []


def test_lint_invalid_file_returns_diagnostic_with_structured_fields(tmp_path):
    p = tmp_path / "bad.puml"
    p.write_text(INVALID_PUML, encoding="utf-8")
    diags = lint(p)
    assert len(diags) == 1
    d = diags[0]
    assert d.level == "error"
    # New: structured fields are populated from -ttxt parsing.
    assert d.line == 2
    assert d.column is not None and d.column >= 1
    assert "bogus" in d.snippet
    assert d.description is not None and "Syntax Error" in d.description
    # Full message is the diagnostic block — show that all key parts
    # are present (verbatim from plantuml).
    assert "@startuml" in d.message
    assert "^" in d.message


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


def test_lint_text_invalid_populates_structured_fields():
    diags = lint_text(INVALID_PUML)
    assert len(diags) == 1
    d = diags[0]
    assert d.line == 2
    assert "bogus" in d.snippet
    assert "Syntax Error" in d.description


def test_lint_text_rejects_non_string():
    with pytest.raises(PlantUmlError, match="expects str"):
        lint_text(b"@startuml\nA -> B\n@enduml")


def test_lint_text_with_unicode_content():
    """CJK content is valid puml; lint_text shouldn't complain about
    encoding or anything."""
    src = "@startuml\ntitle 测试\n甲 -> 乙 : 你好\n@enduml"
    assert lint_text(src) == []


# --- _run_pipe_ttxt rejects non-string ----------------------------------

def test_run_pipe_ttxt_rejects_non_string():
    with pytest.raises(PlantUmlError, match="expects str"):
        _run_pipe_ttxt(b"@startuml\nA -> B\n@enduml")


# --- JVM-level failure surfaces as PlantUmlError, not a fake "syntax error"

def test_run_pipe_ttxt_raises_on_jvm_failure_with_no_stdout(monkeypatch):
    """If plantuml itself fails to start (corrupt jar / missing JRE /
    OOM at JVM init), `_run_pipe_ttxt` must raise :class:`PlantUmlError`
    naming the upstream stderr — NOT silently return "" which would
    be parsed downstream as a syntax error of the user's puml.

    Reviewer concern from PR #5: the day someone hits a real infra
    failure, "plantuml said your puml is broken" is a misleading
    diagnostic; the real cause should bubble up.
    """
    from pyplantuml import _diagnose as diag_mod
    import subprocess as sp

    class _FakeProc(object):
        def __init__(self):
            self.returncode = 1
            self.stdout = b""
            self.stderr = b"Error: Could not find or load main class net.sourceforge.plantuml.Run\n"

    monkeypatch.setattr(diag_mod.subprocess, "run", lambda *a, **k: _FakeProc())
    with pytest.raises(PlantUmlError) as exc:
        _run_pipe_ttxt("@startuml\nA -> B\n@enduml")
    msg = str(exc.value)
    assert "rc=1" in msg
    assert "Could not find or load main class" in msg


def test_run_pipe_ttxt_raises_on_jvm_failure_with_empty_stderr(monkeypatch):
    """Even when stderr is empty (e.g. the JVM segfaulted before
    writing anything), still raise rather than silently returning ''.
    The placeholder "(empty)" makes it obvious in the error string
    that no upstream message was available."""
    from pyplantuml import _diagnose as diag_mod

    class _FakeProc(object):
        def __init__(self):
            self.returncode = 137  # 128 + SIGKILL — OOM-killer style
            self.stdout = b""
            self.stderr = b""

    monkeypatch.setattr(diag_mod.subprocess, "run", lambda *a, **k: _FakeProc())
    with pytest.raises(PlantUmlError, match=r"rc=137.*\(empty\)"):
        _run_pipe_ttxt("@startuml\nA -> B\n@enduml")


# --- fallback path: -checkonly said error but -ttxt didn't surface a block

def test_lint_fallback_when_ttxt_unparseable_with_text(monkeypatch):
    """If -ttxt returns text without the [From ...] header (defensive
    path for plantuml versions that might one day change format),
    fall back to a flat Diagnostic with the raw text as message."""
    from pyplantuml import _diagnose as diag_mod

    monkeypatch.setattr(
        diag_mod, "_run_pipe_ttxt",
        lambda _src: "weirdly formatted upstream message\n",
    )
    out = diag_mod._diagnostics_via_ttxt("any source", returncode=200)
    assert len(out) == 1
    assert out[0].message == "weirdly formatted upstream message"
    assert out[0].line is None
    assert out[0].column is None


def test_lint_fallback_when_ttxt_empty(monkeypatch):
    """When -ttxt returns nothing parseable AND nothing on stdout,
    synthesize a placeholder message so the Diagnostic still carries
    the returncode signal."""
    from pyplantuml import _diagnose as diag_mod

    monkeypatch.setattr(diag_mod, "_run_pipe_ttxt", lambda _src: "")
    out = diag_mod._diagnostics_via_ttxt("any source", returncode=42)
    assert len(out) == 1
    assert "code 42" in out[0].message
