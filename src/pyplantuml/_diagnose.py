"""Structured lint diagnostics + plantuml ``-ttxt`` parsing.

PlantUML emits a rich, human-readable diagnostic block in its
``-pipe -ttxt`` mode whenever a source has a syntax error::

    [From string (line 2) ]

    @startuml
    A --bogus-> B
    ^^^^^
     Syntax Error?

This format is **stable across all plantuml versions we tested**
(1.2020.7 through 1.2026.2 + ``latest``).  Newer versions append
extra context (e.g. ``" (Assumed diagram type: sequence)"``) which
this parser preserves verbatim in the ``description`` field.

The parser returns ``None`` when the input doesn't look like an
error block (e.g., a successfully rendered ASCII-art diagram), so
callers can use it as a "is this an error?" detector too.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import (
    JAR_PATH,
    PlantUmlError,
    _build_env_and_java_args,
    _java_bin,
)
from . import run as _run
from .diagnostics import _dataclass_like


# --- Diagnostic ----------------------------------------------------------

@_dataclass_like
class Diagnostic(object):
    """A single lint diagnostic.

    Fields
    ------
    level : str
        Currently always ``"error"``.
    line : int | None
        1-based line number plantuml flagged (parsed from the
        ``-ttxt`` ``[From string (line N) ]`` header).
    column : int | None
        1-based column of the caret pointer (``^^^^^``).
    message : str
        The full plantuml-emitted diagnostic block — what you'd
        want to show a human or pass to an LLM.
    snippet : str | None
        The exact source line that was flagged (one line above the
        caret in the diagnostic block).
    description : str | None
        The bare error description on its own line — typically
        ``"Syntax Error?"``.  Newer plantuml versions append extra
        context such as ``"Syntax Error? (Assumed diagram type:
        sequence)"`` which is preserved verbatim.
    """
    __fields__ = (
        "level", "line", "column", "message", "snippet", "description",
    )

    def __init__(
        self,
        level,
        line=None,
        column=None,
        message="",
        snippet=None,
        description=None,
    ):
        self.level = level
        self.line = line
        self.column = column
        self.message = message
        self.snippet = snippet
        self.description = description


# --- diagnostic parsing --------------------------------------------------

# `^` carets followed only by `^` and whitespace; rstrip handles plantuml's
# fixed-width padding on each output line.
_CARET_RE = re.compile(r"^\s*\^+\s*$")
# `[From string (line 2) ]` or  `[From file: /path (line 2) ]`
_HEADER_LINE_RE = re.compile(r"\(line\s+(\d+)\s*\)")


def _parse_ttxt_diagnostic(text):
    """Parse plantuml ``-ttxt`` output into a structured diagnostic dict.

    Returns ``None`` when ``text`` doesn't look like an error block —
    handy as a boolean "is this an error?" check.

    Returns a dict with keys:
        ``line``        -- int | None
        ``column``      -- int | None  (1-based caret position)
        ``snippet``     -- str | None  (the flagged source line)
        ``description`` -- str | None
        ``raw``         -- str         (the full block, stripped of
                                        plantuml's fixed-width padding)
    """
    if not text:
        return None
    # Quick filter: every error block plantuml emits since 1.2020 has
    # both the header marker and a caret line.  Avoid a deep parse
    # of the multi-line ASCII-art that's emitted for valid sources.
    if "[From " not in text:
        return None

    raw_lines = text.splitlines()
    # Strip plantuml's per-line trailing padding so column-counting
    # (which uses the caret line's leading whitespace) is based on
    # printable characters.
    stripped = [line.rstrip() for line in raw_lines]
    raw = "\n".join(stripped).rstrip("\n")

    # Header line — extract line number.
    line_num = None
    for L in stripped:
        m = _HEADER_LINE_RE.search(L)
        if m:
            line_num = int(m.group(1))
            break

    # Caret line — find row of `^^^^^`.
    caret_idx = None
    for i, L in enumerate(stripped):
        if L and _CARET_RE.match(L):
            caret_idx = i
            break

    column = snippet = description = None
    if caret_idx is not None:
        caret_line = stripped[caret_idx]
        # 1-based column where the carets start.  Use the original
        # (un-stripped) source row for a faithful column count, since
        # leading whitespace there is what plantuml actually pointed to.
        original_caret = raw_lines[caret_idx]
        leading_ws = len(original_caret) - len(original_caret.lstrip(" \t"))
        column = leading_ws + 1
        if caret_idx > 0:
            snippet = stripped[caret_idx - 1].rstrip() or None
        if caret_idx + 1 < len(stripped):
            description = stripped[caret_idx + 1].strip() or None

    return {
        "line": line_num,
        "column": column,
        "snippet": snippet,
        "description": description,
        "raw": raw,
    }


def _run_pipe_ttxt(source):
    """Run ``plantuml -pipe -ttxt`` on ``source`` (str), capture stdout.

    Used by :func:`lint_text` and the strict modes of :func:`render_text`
    / :func:`render_bytes`.  Returns the stdout text (which is either
    the rendered ASCII-art diagram or — for invalid sources — the
    diagnostic block).

    Raises :class:`PlantUmlError` when plantuml itself fails to start
    (non-zero exit AND empty stdout — almost certainly a corrupt jar,
    missing JRE, OOM at JVM init, or similar infra problem rather than
    a syntax error in ``source``).  Surfacing this here prevents the
    caller from synthesising a misleading "syntax error?" diagnostic
    against the user's puml when the real cause is the wrapper's own
    runtime.
    """
    if not isinstance(source, str):
        raise PlantUmlError(
            "_run_pipe_ttxt expects str, got {}".format(type(source).__name__)
        )
    auto_env, java_extra = _build_env_and_java_args()
    cmd = [str(_java_bin())]
    cmd.extend(java_extra)
    cmd.extend(["-jar", str(JAR_PATH), "-pipe", "-ttxt"])
    proc = subprocess.run(
        cmd,
        input=source.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=auto_env,
    )
    if proc.returncode != 0 and not proc.stdout:
        stderr = (
            proc.stderr.decode("utf-8", errors="replace")
            if proc.stderr
            else ""
        )
        raise PlantUmlError(
            "_run_pipe_ttxt: plantuml exited rc={} with no stdout; "
            "stderr: {}".format(
                proc.returncode,
                stderr.strip()[:500] or "(empty)",
            )
        )
    return proc.stdout.decode("utf-8", errors="replace")


# --- public API ----------------------------------------------------------

def lint(source_path):
    """Lint a .puml file path; return a list of :class:`Diagnostic`.

    Empty list = source is valid (or plantuml's lenient parser
    accepted it; missing ``@enduml`` and undefined aliases pass).

    Bad sources yield a single Diagnostic whose ``message`` is the
    plantuml ``-ttxt`` diagnostic block (with line/column/snippet/
    description also populated).

    Raises :class:`PlantUmlError` if the file does not exist.
    """
    src = Path(source_path)
    if not src.exists():
        raise PlantUmlError("source not found: {}".format(src))
    # Fast pre-flight via -checkonly: avoids a full -ttxt render for
    # valid sources (the common case).
    proc = _run(["-checkonly", str(src)], capture_output=True, check=False)
    if proc.returncode == 0:
        return []
    # Source is invalid — re-run via -ttxt to get the structured block.
    return _diagnostics_via_ttxt(src.read_text(encoding="utf-8"), proc.returncode)


def lint_text(source):
    """Lint puml source as a string; same return semantics as :func:`lint`."""
    if not isinstance(source, str):
        raise PlantUmlError(
            "lint_text expects str, got {}".format(type(source).__name__)
        )
    fd, tmp = tempfile.mkstemp(suffix=".puml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(source)
        return lint(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:  # pragma: no cover - rare race on shared tmp
            pass


def _diagnostics_via_ttxt(source_text, returncode):
    """Run -ttxt against ``source_text`` and parse the diagnostic.

    Always returns a list with at least one Diagnostic — falling back
    to a synthetic one if -ttxt didn't yield a parseable block (e.g.
    the source had an error -checkonly caught but -ttxt rendered
    around).
    """
    text = _run_pipe_ttxt(source_text)
    info = _parse_ttxt_diagnostic(text)
    if info is None:
        # -checkonly said error but -ttxt didn't surface a block.
        # Fall back to a flat Diagnostic with whatever text we have.
        msg = (text.strip() or
               "syntax error (PlantUML exited with code {})".format(returncode))
        return [
            Diagnostic(
                level="error",
                line=None, column=None,
                message=msg,
                snippet=None, description=None,
            )
        ]
    return [
        Diagnostic(
            level="error",
            line=info["line"],
            column=info["column"],
            message=info["raw"],
            snippet=info["snippet"],
            description=info["description"],
        )
    ]
