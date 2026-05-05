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
from __future__ import annotations

import sys
from typing import List

import click

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
