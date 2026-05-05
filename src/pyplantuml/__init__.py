from __future__ import annotations

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
    "render",
    "check",
    "run",
    "PlantUmlError",
    "version",
]

__version__ = "0.1.0"

_PKG_DIR = Path(__file__).resolve().parent
JAR_PATH: Path = _PKG_DIR / "plantuml.jar"


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
    jre_dir = _PKG_DIR / "jre"
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


JAVA_BIN: Path = _PKG_DIR / "jre" / "bin" / ("java.exe" if os.name == "nt" else "java")


def _cache_dir() -> Path:
    """Per-user, writable directory for fontconfig cache. Stable across runs."""
    base = (
        os.environ.get("XDG_CACHE_HOME")
        or (os.environ.get("LOCALAPPDATA") if os.name == "nt" else None)
        or str(Path.home() / ".cache")
    )
    cache = Path(base) / "pyplantuml" / "fontconfig"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _ensure_fonts_conf(font_dir: Path) -> Path:
    """Materialize fonts.conf with absolute paths into a stable cache location."""
    template = (_PKG_DIR / "runtime" / "fonts.conf.template").read_text(encoding="utf-8")
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
    runtime_dir = _PKG_DIR / "runtime" / plat
    if plat.startswith("linux") and runtime_dir.exists():
        lib_dir = runtime_dir / "lib"
        font_dir = runtime_dir / "fonts"
        # Prepend our libfontconfig.so / freetype / etc. so the JRE finds them
        old = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{lib_dir}{':' + old if old else ''}"
        )
        # Force fontconfig to read OUR config that points only at our fonts
        env["FONTCONFIG_FILE"] = str(_ensure_fonts_conf(font_dir))
        env["FONTCONFIG_PATH"] = str(font_dir)
        # Tell AWT directly where to find TTFs (extra belt-and-suspenders)
        java_args.append(f"-Dsun.java2d.fontpath={font_dir}")
        # Some JDK builds prefer this property name
        java_args.append(f"-Dsun.font.fontconfig.disable=false")

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
    """Invoke the bundled PlantUML jar with arbitrary CLI args."""
    auto_env, java_extra = _build_env_and_java_args()
    if env is not None:
        # caller-supplied env wins, but keep our LD_LIBRARY_PATH/FONTCONFIG_*
        merged = {**auto_env, **env}
    else:
        merged = auto_env
    cmd = _build_cmd(args, java_extra)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=merged,
        capture_output=capture_output,
        text=capture_output,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise PlantUmlError(
            f"plantuml exited with {proc.returncode}: {' '.join(cmd)}"
        )
    return proc


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
    """Console entry point: pass-through to PlantUML CLI."""
    proc = run(sys.argv[1:], check=False)
    return proc.returncode
