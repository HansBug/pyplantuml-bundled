"""In-memory rendering helpers — string/bytes in, image bytes out.

Convenience wrappers over plantuml's ``-pipe`` mode for the common case
where the caller has puml as a Python string and wants the rendered
image bytes back without a disk round-trip.

Both :func:`render_text` and :func:`render_bytes` accept a ``strict``
flag.  By default (``strict=False``) plantuml's lenient behaviour is
preserved: a syntactically broken source produces an "error image"
(the rendered text describing the problem) which is returned verbatim
as bytes — matching what a user would see if they ran ``plantuml``
on the command line.

With ``strict=True`` the same broken source raises a
:class:`PlantUmlSyntaxError` whose message is the structured ``-ttxt``
diagnostic block (line number, source snippet, caret pointer, error
description).  That text is the canonical thing to show a human or
forward to an LLM trying to repair the puml.

These functions are re-exported from the top-level package, so prefer
``pyplantuml.render_text`` / ``pyplantuml.render_bytes`` over importing
the private module directly.
"""
import os
import subprocess
from pathlib import Path

from . import (
    JAR_PATH,
    PlantUmlError,
    PlantUmlSyntaxError,
    _build_env_and_java_args,
    _java_bin,
)


def _run_pipe(source_bytes, fmt, extra_args=()):
    """Run ``plantuml -pipe -t<fmt>`` once.  Returns CompletedProcess."""
    auto_env, java_extra = _build_env_and_java_args()
    cmd = [str(_java_bin())]
    cmd.extend(java_extra)
    cmd.extend(["-jar", str(JAR_PATH), "-pipe", "-t" + fmt])
    cmd.extend(list(extra_args))
    return subprocess.run(
        cmd,
        input=source_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=auto_env,
    )


def _raise_syntax_error_from_source(source, returncode):
    """Re-render in -ttxt to get the human-readable diagnostic, then
    raise :class:`PlantUmlSyntaxError`.  Imported lazily to avoid a
    circular import at module-load time (``_diagnose`` imports from
    this module's package)."""
    from ._diagnose import _run_pipe_ttxt, _parse_ttxt_diagnostic
    diag_text = _run_pipe_ttxt(source)
    info = _parse_ttxt_diagnostic(diag_text)
    if info is None:
        # -ttxt didn't yield a parseable block — fall back to whatever
        # plantuml emitted (might be empty or a partial render).
        msg = (
            diag_text.strip()
            or "PlantUML reported a syntax error (rc={})".format(returncode)
        )
        raise PlantUmlSyntaxError(msg, returncode=returncode)
    raise PlantUmlSyntaxError(
        info["raw"],
        line=info["line"],
        column=info["column"],
        snippet=info["snippet"],
        description=info["description"],
        returncode=returncode,
    )


def render_text(source, fmt="png", strict=False, extra_args=()):
    """Render puml source from a string and return the rendered bytes.

    Pipes the source through ``plantuml -pipe -t<fmt>``.

    Parameters
    ----------
    source : str
        Full puml source, including ``@startuml`` / ``@enduml``.
    fmt : str
        Output format passed to plantuml as ``-t<fmt>`` (``png``,
        ``svg``, ``txt``, ``utxt``, ``pdf``, ``vdx``, ...).
    strict : bool, default False
        If False, return whatever bytes plantuml produced even when
        the source has a syntax error (an "error image" describing
        the problem).  If True, raise :class:`PlantUmlSyntaxError`
        with the structured diagnostic instead — see the
        :class:`PlantUmlSyntaxError` docstring for the available
        fields.
    extra_args : Iterable[str]
        Additional CLI tokens forwarded verbatim after the format flag.

    Returns
    -------
    bytes
        The raw image bytes plantuml emitted on stdout.

    Raises
    ------
    PlantUmlSyntaxError
        Only when ``strict=True`` and plantuml flagged the source as
        invalid.  Subclass of :class:`PlantUmlError`, so existing
        ``except PlantUmlError`` handlers still catch it.
    PlantUmlError
        If ``source`` is not a ``str``, or if plantuml emitted no
        output at all (unknown format flag, JVM crash on startup).
    """
    if not isinstance(source, str):
        raise PlantUmlError(
            "render_text expects str, got {}".format(type(source).__name__)
        )
    proc = _run_pipe(source.encode("utf-8"), fmt, extra_args)
    if not proc.stdout:
        stderr_text = (
            proc.stderr.decode("utf-8", errors="replace")
            if proc.stderr
            else ""
        )
        raise PlantUmlError(
            "render_text produced no output (rc={}); stderr: {}".format(
                proc.returncode,
                stderr_text.strip()[:500] or "(empty)",
            )
        )
    if strict and proc.returncode != 0:
        # Plantuml flagged the source as invalid AND caller asked for
        # strict feedback.  Re-render in -ttxt to extract the
        # human-readable diagnostic, then raise.
        _raise_syntax_error_from_source(source, proc.returncode)
    return proc.stdout


def render_bytes(source_path, fmt="png", strict=False, extra_args=()):
    """Render a .puml file and return the rendered bytes (no disk write).

    Equivalent to reading ``source_path`` as UTF-8 and forwarding to
    :func:`render_text`, with an explicit existence check up front so the
    error message names the missing file rather than complaining about
    encoding.

    Parameters mirror :func:`render_text` (including ``strict``);
    ``source_path`` is anything accepted by :class:`pathlib.Path`.
    """
    src = Path(source_path)
    if not src.exists():
        raise PlantUmlError("source not found: {}".format(src))
    return render_text(
        src.read_text(encoding="utf-8"),
        fmt=fmt,
        strict=strict,
        extra_args=extra_args,
    )
