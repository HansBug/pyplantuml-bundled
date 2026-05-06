"""Structured lint diagnostics for puml sources.

PlantUML's ``-checkonly`` is a binary pass/fail check: the CLI does not
expose per-line error info.  When a source has errors, :func:`lint`
returns a single :class:`Diagnostic` whose ``message`` field carries
plantuml's raw stderr text; ``line`` and ``column`` are always ``None``.
Future plantuml versions may provide structured output, at which point
this layer can populate them without breaking the API shape.
"""
import os
import tempfile
from pathlib import Path

from . import PlantUmlError
from . import run as _run
from .diagnostics import _dataclass_like


@_dataclass_like
class Diagnostic(object):
    """A single lint diagnostic.

    Fields
    ------
    level : str
        Currently always ``"error"``.
    line : int | None
        Always ``None`` until plantuml exposes line info.
    column : int | None
        Always ``None`` until plantuml exposes column info.
    message : str
        plantuml's raw stderr text, or a synthetic explanation if
        plantuml exited non-zero with empty stderr.
    snippet : str | None
        Reserved for future use; always ``None`` for now.
    """
    __fields__ = ("level", "line", "column", "message", "snippet")

    def __init__(self, level, line=None, column=None, message="", snippet=None):
        self.level = level
        self.line = line
        self.column = column
        self.message = message
        self.snippet = snippet


def lint(source_path):
    """Lint a .puml file path; return a list of Diagnostics.

    Empty list = source is valid (or plantuml's lenient parser
    accepted it; missing ``@enduml`` and undefined aliases pass).

    Raises :class:`PlantUmlError` if the file does not exist.
    """
    src = Path(source_path)
    if not src.exists():
        raise PlantUmlError("source not found: {}".format(src))
    proc = _run(["-checkonly", str(src)], capture_output=True, check=False)
    return _parse_diagnostics(
        proc.returncode,
        proc.stderr if proc.stderr is not None else "",
    )


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


def _strip_known_noise(stderr_text):
    """Drop stderr lines that are NOT plantuml syntax errors.

    Linux carries the bundled libfontconfig schema warning ("unknown
    element 'reset-dirs'") that the launcher otherwise routes through
    `2>/dev/null` for the CLI; openjdk has emitted "illegal reflective
    access" deprecation warnings in past versions.  None of these
    indicate a problem with the puml source, so we filter them out
    before deciding what to report.
    """
    drop_prefixes = (
        "Fontconfig warning",
        "Fontconfig error",
        "WARNING: An illegal reflective access",
        "WARNING: Please consider reporting",
        "WARNING: Use --illegal-access",
        "WARNING: All illegal access operations",
    )
    keep = []
    for line in stderr_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in drop_prefixes):
            continue
        keep.append(stripped)
    return "\n".join(keep)


def _parse_diagnostics(returncode, stderr_text):
    """Translate (returncode, stderr_text) into a Diagnostic list.

    Returncode is the authoritative pass/fail signal — plantuml's
    -checkonly returns 0 for valid input and a non-zero code (typically
    200) for syntax errors.  Stderr noise (fontconfig warnings, JVM
    deprecation messages) is filtered out so we don't report false
    positives.

    Plain function so tests can exercise the parsing logic without
    spawning a JVM.
    """
    if returncode == 0:
        return []
    msg = _strip_known_noise(stderr_text).strip()
    if not msg:
        msg = "syntax error (PlantUML exited with code {})".format(returncode)
    return [
        Diagnostic(
            level="error",
            line=None,
            column=None,
            message=msg,
            snippet=None,
        )
    ]
