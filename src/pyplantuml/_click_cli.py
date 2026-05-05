"""
Click-based CLI for ``plantuml``.

The default command (no sub-command) forwards every argument straight to
the bundled ``plantuml.jar`` — this preserves byte-for-byte CLI parity
with upstream PlantUML.  Named sub-commands handle features that are
purely Python-side, the most important being ``selfcheck``.

Why a sub-command-with-passthrough rather than a single argv parser:

- ``plantuml -tpng diagram.puml`` must keep working.  The bundled jar
  owns its own argument grammar (some flags start with single dash,
  some with double) and we do not re-parse it.
- ``plantuml selfcheck`` should feel like a normal Click sub-command
  (``--help``, ``--no-color``, etc.).
"""
import os
import sys
from typing import List

# Provide UTF-8 hints for any subprocess we later spawn (java, ldd …)
# before importing click.  Setting them here does not change the
# *current* interpreter's filesystem encoding (that was frozen at
# Python startup), so the click monkey-patch below is what protects
# this process.  Setting them does, however, propagate to children.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if not os.environ.get("LC_ALL"):
    os.environ["LC_ALL"] = "C.UTF-8"
if not os.environ.get("LANG"):
    os.environ["LANG"] = "C.UTF-8"

import click


def _neutralize_click_locale_check():
    """Disable click 7.x's ``_unicodefun._verify_python3_env``.

    On a 'clean' container (debian-slim / ubuntu / alpine without
    ``LANG``) Python's filesystem encoding defaults to ASCII, and
    click 7's check then refuses to run with::

        RuntimeError: Click will abort further execution because
        Python 3 was configured to use ASCII as encoding for the
        environment.

    Click 8.1.0 removed the check entirely (issue pallets/click#2198),
    relying on PEP 538 / PEP 540 instead.  Replicate that behavior on
    click 7 so our portable executables — whose entire selling point is
    "works inside a scratch container" — do not fall over.

    We must patch every module that imported the symbol by name; in
    click 7 ``click/core.py`` does ``from ._unicodefun import
    _verify_python3_env`` at import time and captures its own reference,
    so patching ``click._unicodefun`` alone has no effect.
    """
    noop = lambda: None  # noqa: E731
    for mod_name in ("click.core", "click._unicodefun"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr in ("_verify_python_env", "_verify_python3_env"):
            if hasattr(mod, attr):
                try:
                    setattr(mod, attr, noop)
                except Exception:
                    pass


_neutralize_click_locale_check()

from . import __version__, run as _run, JAR_PATH, JAVA_BIN


PASSTHROUGH_CONTEXT = {
    # Click would otherwise reject unknown flags like ``-tpng`` because
    # they look like options.  Tell it to leave them alone.
    "ignore_unknown_options": True,
    "allow_extra_args": True,
    "help_option_names": ["-h", "--help"],
}


@click.group(
    invoke_without_command=True,
    context_settings=PASSTHROUGH_CONTEXT,
)
@click.version_option(__version__, "-V", "--version-pyplantuml",
                     prog_name="pyplantuml-bundled")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """\
    PlantUML with a bundled JRE — works offline, no system Java required.

    \b
    Common usage:
      plantuml -tpng diagram.puml      # render to PNG (forwarded to plantuml.jar)
      plantuml -tsvg diagram.puml      # render to SVG
      plantuml -checkonly diagram.puml # static syntax check
      plantuml selfcheck               # run the Python-side diagnostic battery
      plantuml info                    # show paths and bundled versions
      plantuml --help                  # this help text

    Any argument that does not match a known Click sub-command is
    forwarded verbatim to the embedded ``plantuml.jar`` so this binary
    is a drop-in replacement for ``java -jar plantuml.jar``.
    """
    if ctx.invoked_subcommand is not None:
        return
    # No sub-command — forward raw argv to the bundled jar.
    raw: List[str] = list(ctx.args)
    if not raw:
        click.echo(ctx.get_help())
        ctx.exit(0)
    proc = _run(raw, check=False)
    ctx.exit(proc.returncode)


@cli.command(name="selfcheck", context_settings=PASSTHROUGH_CONTEXT)
@click.option("--no-color", is_flag=True, default=False,
              help="Disable ANSI colour even on a TTY.")
@click.option("--color", "force_color", is_flag=True, default=False,
              help="Force-enable ANSI colour even on a non-TTY (CI logs).")
@click.option("--no-env", is_flag=True, default=False,
              help="Skip the environment dump for shorter output.")
def cmd_selfcheck(no_color: bool, force_color: bool, no_env: bool) -> None:
    """Run the diagnostic battery and exit non-zero on any failure.

    Verifies every aspect of the install that could plausibly break a
    PlantUML render: the JRE module set, the bundled jar's integrity,
    the Linux fontconfig + freetype + font payload, the cache-dir
    writability, an end-to-end PNG / SVG render, CJK glyph rendering,
    and (when running as a PyInstaller frozen exe) the ``_MEIPASS``
    layout.  Every case is wrapped in a ``BaseException`` catch so the
    runner finishes even if half the install is broken.
    """
    from . import diagnostics
    args: List[str] = []
    if no_color:
        args.append("--no-color")
    if force_color:
        args.append("--color")
    if no_env:
        args.append("--no-env")
    rc = diagnostics.run_selfcheck(args)
    raise SystemExit(rc)


@cli.command(name="info")
def cmd_info() -> None:
    """Print bundled paths and PlantUML / JRE versions."""
    from . import version
    click.echo("pyplantuml-bundled  : {}".format(__version__))
    click.echo("PKG_DIR             : {}".format(_locate_pkg_dir()))
    click.echo("JAR_PATH            : {}".format(JAR_PATH))
    click.echo("JAVA_BIN            : {}".format(JAVA_BIN))
    click.echo("")
    try:
        click.echo(version())
    except BaseException as exc:
        click.echo("(could not query version: {!r})".format(exc), err=True)
        raise SystemExit(1)


def _locate_pkg_dir() -> str:
    from . import PKG_DIR
    return str(PKG_DIR)


def main() -> int:
    """Programmatic entry, returns the exit code without exiting."""
    # Plantuml.jar's CLI uses single-dash flags for everything
    # (``-version``, ``-help``, ``-tpng``, ``-checkonly``, ``-tsvg``,
    # ``-DPLANTUML_LIMIT_SIZE=…``, …).  Click cannot parse them
    # cleanly — ``-version`` for instance is too short to look like a
    # long option (which click expects to start with ``--``) so click
    # falls through to subcommand lookup and reports ``Error: No such
    # command '-version'``.  Detect this case before click sees it
    # and forward the whole argv straight to the bundled jar, the
    # same way the no-arg default command would.
    #
    # Click's own short flags (``-h`` / ``--help`` / ``-V`` /
    # ``--version-pyplantuml``) and our two real subcommands
    # (``info`` / ``selfcheck``) are explicitly preserved so they
    # still go through click.
    _KNOWN_CLICK_FLAGS = ("-h", "--help", "-V", "--version-pyplantuml")
    _KNOWN_SUBCOMMANDS = ("info", "selfcheck")
    if len(sys.argv) > 1:
        first = sys.argv[1]
        if (first not in _KNOWN_SUBCOMMANDS
                and first.startswith("-")
                and first not in _KNOWN_CLICK_FLAGS):
            try:
                proc = _run(sys.argv[1:], check=False)
                return proc.returncode
            except BaseException as exc:
                sys.stderr.write("plantuml: {}\n".format(exc))
                return 1
    try:
        cli.main(args=sys.argv[1:], standalone_mode=False)
        return 0
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, bool):
            return int(code)
        if isinstance(code, int):
            return code
        try:
            return int(code)
        except (TypeError, ValueError):
            return 1
    except click.exceptions.UsageError as e:
        e.show()
        return e.exit_code
    except click.exceptions.Abort:
        click.echo("Aborted.", err=True)
        return 130
