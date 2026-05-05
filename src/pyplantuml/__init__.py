import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

__all__ = [
    "JAR_PATH",
    "JAVA_BIN",
    "PKG_DIR",
    "render",
    "check",
    "run",
    "PlantUmlError",
    "version",
    "__version__",
    "__plantuml_version__",
]

# Versioning convention: <plantuml-3-segments>.<wrapper-revision>.
# First three segments mirror the bundled plantuml.jar; the trailing
# segment is bumped on wrapper-only fixes (CI, staging, click compat,
# new platform support, …) without an upstream PlantUML change.
# Same scheme as jdk4py.  See AGENTS.md for the rationale.
__version__ = "1.2024.7.1"
__plantuml_version__ = ".".join(__version__.split(".")[:3])


def _resolve_pkg_dir() -> Path:
    """
    Where the bundled `plantuml.jar`, `jre/`, and `runtime/` actually live.

    * In a normal `pip install` the package directory is the parent of
      this file (`Path(__file__).resolve().parent`).
    * In a PyInstaller frozen executable the layout is different:
      `sys._MEIPASS` is the unpacked-resources root, and we put our
      assets under `<_MEIPASS>/pyplantuml/` so the same relative paths
      resolve identically.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "pyplantuml"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


PKG_DIR: Path = _resolve_pkg_dir()
_PKG_DIR = PKG_DIR  # internal alias for legacy code paths

JAR_PATH: Path = PKG_DIR / "plantuml.jar"


class PlantUmlError(RuntimeError):
    """Raised when the embedded PlantUML invocation fails."""


def _platform_key() -> str:
    """Return the runtime/<key> directory name for the current OS+arch."""
    sysname = platform.system()
    machine = platform.machine().lower()
    arch_aliases = {
        "x86_64": "x86_64", "amd64": "x86_64",
        "aarch64": "aarch64", "arm64": "aarch64",
    }
    arch = arch_aliases.get(machine, machine)
    if sysname == "Linux":
        return f"linux-{arch}"
    if sysname == "Darwin":
        return f"macos-{arch}"
    if sysname == "Windows":
        return f"windows-{arch}"
    return f"{sysname.lower()}-{arch}"


def _resolve_java_bin() -> Path:
    jre_dir = PKG_DIR / "jre"
    exe = "java.exe" if os.name == "nt" else "java"
    candidate = jre_dir / "bin" / exe
    if candidate.exists():
        return candidate
    raise PlantUmlError(
        f"bundled JRE not found at {candidate}. "
        "This wheel was likely built without a JRE for your platform; "
        "reinstall a platform-specific wheel or set PYPLANTUML_JAVA env var."
    )


def _java_bin() -> Path:
    override = os.environ.get("PYPLANTUML_JAVA")
    if override:
        p = Path(override)
        if not p.exists():
            raise PlantUmlError(f"PYPLANTUML_JAVA points to missing file: {p}")
        return p
    return _resolve_java_bin()


JAVA_BIN: Path = PKG_DIR / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")


def _cache_dir() -> Path:
    """Per-user, writable directory for fontconfig cache. Stable across runs.

    Falls back through several candidates if the preferred one is not
    writable (read-only $HOME, sandboxed exec, frozen exe in a snap, …)
    so the launcher never crashes just because /home is a squashfs.
    """
    candidates: List[Path] = []
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        candidates.append(Path(xdg) / "pyplantuml" / "fontconfig")
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            candidates.append(Path(local_app) / "pyplantuml" / "fontconfig")
    home = os.environ.get("HOME") or str(Path.home())
    candidates.append(Path(home) / ".cache" / "pyplantuml" / "fontconfig")
    candidates.append(Path(tempfile.gettempdir()) / "pyplantuml-fontconfig")

    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return cand
        except OSError:
            continue
    raise PlantUmlError(
        "no writable cache directory available; tried: "
        + ", ".join(str(c) for c in candidates)
    )


def _ensure_fonts_conf(font_dir: Path) -> Path:
    """Materialize fonts.conf with absolute paths into a stable cache location."""
    template = (PKG_DIR / "runtime" / "fonts.conf.template").read_text(encoding="utf-8")
    cache = _cache_dir()
    rendered = template.replace("{FONT_DIR}", str(font_dir)).replace(
        "{CACHE_DIR}", str(cache)
    )
    out = cache / "fonts.conf"
    if not out.exists() or out.read_text(encoding="utf-8") != rendered:
        out.write_text(rendered, encoding="utf-8")
    return out


def _build_env_and_java_args() -> tuple:
    """
    On Linux we ship libfontconfig + freetype + DejaVu + WenQuanYi MicroHei
    so the JRE can render text (incl. CJK) inside scratch / slim containers
    that have NO system fonts. macOS uses CoreText, Windows uses GDI — both
    bundle their own fonts so we need no extra runtime there.
    """
    env = os.environ.copy()
    java_args: List[str] = [
        "-Djava.awt.headless=true",
        "-Dfile.encoding=UTF-8",
    ]

    plat = _platform_key()

    # macOS Apple Silicon + PyInstaller frozen: hardened-runtime denies
    # the JVM JIT's mmap(PROT_EXEC) regardless of ad-hoc signing or
    # entitlements (com.apple.security.cs.allow-jit is only honoured by
    # Developer-ID signed binaries). Run the JVM in pure interpreter
    # mode there. PlantUML rendering is small enough that the lack of
    # JIT is not noticeable.
    if plat == "macos-aarch64" and getattr(sys, "frozen", False):
        java_args.append("-Xint")
    runtime_dir = PKG_DIR / "runtime" / plat
    if plat.startswith("linux") and runtime_dir.exists():
        lib_dir = runtime_dir / "lib"
        font_dir = runtime_dir / "fonts"
        old = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{lib_dir}{':' + old if old else ''}"
        )
        env["FONTCONFIG_FILE"] = str(_ensure_fonts_conf(font_dir))
        env["FONTCONFIG_PATH"] = str(font_dir)
        java_args.append(f"-Dsun.java2d.fontpath={font_dir}")
        java_args.append("-Dsun.font.fontconfig.disable=false")

    return env, java_args


def _build_cmd(args: Sequence[str], java_extra: Sequence[str]) -> List[str]:
    java = str(_java_bin())
    return [java, *java_extra, "-jar", str(JAR_PATH), *args]


def run(
    args: Sequence[str],
    *,
    cwd: Optional[os.PathLike] = None,
    env: Optional[dict] = None,
    capture_output: bool = False,
    check: bool = True,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Invoke the bundled PlantUML jar with arbitrary CLI args.

    On non-zero exit when ``check=True`` the raised ``PlantUmlError`` carries
    the joined command, the return code, *and* the captured stderr/stdout
    from java itself — important so a self-check failure surfaces the actual
    JVM diagnostic instead of a bare ``plantuml exited with 1``.
    """
    auto_env, java_extra = _build_env_and_java_args()
    merged = {**auto_env, **env} if env is not None else auto_env
    cmd = _build_cmd(args, java_extra)
    # Always capture so we can include the JVM's own message on failure;
    # if the caller asked for capture too, return the captured strings.
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=merged,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    # Convert bytes to str unconditionally — text=True at subprocess level
    # would have done this for us, but we did the capture by hand to keep
    # the failure-path message rich.
    stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""

    if not capture_output:
        # Re-emit on the parent's stdio so callers that do NOT want output
        # captured (the default plantuml CLI mode) still see java's output.
        if stdout:
            try:
                sys.stdout.write(stdout)
                sys.stdout.flush()
            except Exception:
                pass
        if stderr:
            try:
                sys.stderr.write(stderr)
                sys.stderr.flush()
            except Exception:
                pass

    completed = subprocess.CompletedProcess(
        args=proc.args, returncode=proc.returncode,
        stdout=stdout if capture_output else None,
        stderr=stderr if capture_output else None,
    )

    if check and proc.returncode != 0:
        # Trim noisy banners but keep enough to debug:
        def _trim(s: str, head: int = 2000) -> str:
            return s if len(s) <= head else s[:head] + "\n…(truncated)"
        raise PlantUmlError(
            "plantuml exited with {rc}\n"
            "  command : {cmd}\n"
            "  stderr  : {stderr}\n"
            "  stdout  : {stdout}".format(
                rc=proc.returncode,
                cmd=" ".join(cmd),
                stderr=_trim(stderr.strip()) or "(empty)",
                stdout=_trim(stdout.strip()) or "(empty)",
            )
        )
    return completed


def render(
    source: os.PathLike,
    *,
    output_dir: Optional[os.PathLike] = None,
    fmt: str = "png",
    extra_args: Iterable[str] = (),
) -> subprocess.CompletedProcess:
    """Render a .puml file. fmt: png|svg|txt|pdf|...; output_dir defaults to source dir."""
    src = Path(source)
    if not src.exists():
        raise PlantUmlError(f"source not found: {src}")
    args: List[str] = [f"-t{fmt}"]
    if output_dir is not None:
        args += ["-o", str(Path(output_dir).resolve())]
    args += list(extra_args)
    args.append(str(src))
    return run(args)


def check(source: os.PathLike) -> bool:
    """Static check a .puml file. Returns True if valid."""
    proc = run(["-checkonly", str(source)], check=False)
    return proc.returncode == 0


def version() -> str:
    proc = run(["-version"], capture_output=True, check=False)
    return proc.stdout.strip() if proc.stdout else ""


def _cli() -> int:
    """Console entry point. Click is imported lazily so frozen exes that
    omit the diagnostic sub-tree still start. Falls back to a hand-rolled
    pass-through if Click cannot import for any reason."""
    try:
        import click  # noqa: F401
    except Exception as exc:  # pragma: no cover - click is a hard dep, but the
        # whole point of selfcheck is "never crash" — so if click is somehow
        # unimportable on the user's machine we degrade to bare passthrough.
        sys.stderr.write(
            "warning: click failed to import ({!r}); "
            "selfcheck unavailable, forwarding raw args to plantuml.jar.\n"
            .format(exc)
        )
        proc = run(sys.argv[1:], check=False)
        return proc.returncode
    from . import _click_cli  # local import: build the click app on demand
    return _click_cli.main()
