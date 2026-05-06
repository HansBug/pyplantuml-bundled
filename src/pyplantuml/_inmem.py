"""In-memory rendering helpers — string/bytes in, image bytes out.

Convenience wrappers over plantuml's ``-pipe`` mode for the common case
where the caller has puml as a Python string and wants the rendered
image bytes back without a disk round-trip.

These functions are re-exported from the top-level package, so prefer
``pyplantuml.render_text`` / ``pyplantuml.render_bytes`` over importing
the private module directly.
"""
import os
import subprocess
from pathlib import Path
from typing import Iterable

from . import (
    JAR_PATH,
    PlantUmlError,
    _build_env_and_java_args,
    _java_bin,
)


def render_text(
    source,
    fmt="png",
    extra_args=(),
):
    """Render puml source from a string and return the rendered bytes.

    Pipes the source through ``plantuml -pipe -t<fmt>``.  Use ``lint()``
    first if you need to validate before rendering — this function
    returns plantuml's rendered output even for syntactically broken
    sources (plantuml in that case emits an error image whose visible
    contents describe the syntax problem).

    Parameters
    ----------
    source : str
        Full puml source, including ``@startuml`` / ``@enduml``.
    fmt : str
        Output format passed to plantuml as ``-t<fmt>`` (``png``,
        ``svg``, ``txt``, ``utxt``, ``pdf``, ``vdx``, ...).
    extra_args : Iterable[str]
        Additional CLI tokens forwarded verbatim after the format flag.

    Returns
    -------
    bytes
        The raw image bytes plantuml emitted on stdout.

    Raises
    ------
    PlantUmlError
        If ``source`` is not a ``str``, or if plantuml emitted no
        output at all (e.g. an unknown format flag, JVM crash on
        startup).
    """
    if not isinstance(source, str):
        raise PlantUmlError(
            "render_text expects str, got {}".format(type(source).__name__)
        )
    auto_env, java_extra = _build_env_and_java_args()
    cmd = [str(_java_bin())]
    cmd.extend(java_extra)
    cmd.extend([
        "-jar", str(JAR_PATH),
        "-pipe",
        "-t" + fmt,
    ])
    cmd.extend(list(extra_args))
    proc = subprocess.run(
        cmd,
        input=source.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=auto_env,
    )
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
    return proc.stdout


def render_bytes(
    source_path,
    fmt="png",
    extra_args=(),
):
    """Render a .puml file and return the rendered bytes (no disk write).

    Equivalent to reading ``source_path`` as UTF-8 and forwarding to
    ``render_text``, with an explicit existence check up front so the
    error message names the missing file rather than complaining about
    encoding.

    Parameters mirror :func:`render_text`; ``source_path`` is anything
    accepted by :class:`pathlib.Path`.
    """
    src = Path(source_path)
    if not src.exists():
        raise PlantUmlError("source not found: {}".format(src))
    return render_text(
        src.read_text(encoding="utf-8"),
        fmt=fmt,
        extra_args=extra_args,
    )
