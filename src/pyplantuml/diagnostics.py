"""
End-to-end self-check for ``pyplantuml-bundled``.

Powers the ``plantuml selfcheck`` CLI flag and is the **last line of
defence** when an install is broken: every case is isolated, every
exception is caught and reported, and the runner finishes even when
most cases fail. Output is ANSI-colored and structured so a human or an
LLM debugger can act on it directly.

Design constraints (mirroring the pyfcstm pattern):

1. **Never crash.** Including ``KeyboardInterrupt`` and ``SystemExit``,
   a fault in any case can never abort the runner.
2. **No required third-party dependency.** The only deps are stdlib +
   the package itself. ``click`` etc. would be unavailable inside a
   PyInstaller frozen build that didn't bundle them, and that build is
   precisely the thing this module is meant to diagnose.
3. **Two perspectives covered.** Cases probe the install both as if it
   were a regular ``pip install`` (file layout under site-packages) and
   as if it were a PyInstaller frozen exe (``sys._MEIPASS``).
4. **Network is never required.** Every render-path case uses an
   inline puml string and a tempdir; no DNS, no HTTP.

The module exposes :func:`run_selfcheck` for the CLI glue.
"""
from __future__ import annotations

import datetime
import os
import platform
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------- #
# Result types
# ---------------------------------------------------------------------------- #


@dataclass
class Case:
    name: str
    method: str
    func: Callable[[], None]
    remediation: Optional[str] = None


@dataclass
class Result:
    case: Case
    status: str  # "PASS" | "FAIL"
    elapsed_ms: float
    error: Optional[BaseException] = None
    traceback_text: Optional[str] = None


# ---------------------------------------------------------------------------- #
# ANSI painter (no click dependency)
# ---------------------------------------------------------------------------- #


_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}


class _Painter:
    def __init__(self, force_color: Optional[bool] = None) -> None:
        if force_color is None:
            # Honour NO_COLOR (https://no-color.org/) and disable on non-TTY.
            if "NO_COLOR" in os.environ:
                self.enabled = False
            elif os.environ.get("FORCE_COLOR"):
                self.enabled = True
            else:
                try:
                    self.enabled = sys.stdout.isatty()
                except Exception:
                    self.enabled = False
        else:
            self.enabled = bool(force_color)

    def style(self, text: str, *, fg: Optional[str] = None,
              bold: bool = False, dim: bool = False) -> str:
        if not self.enabled:
            return text
        prefix = ""
        if bold:
            prefix += _ANSI["bold"]
        if dim:
            prefix += _ANSI["dim"]
        if fg and fg in _ANSI:
            prefix += _ANSI[fg]
        if not prefix:
            return text
        return f"{prefix}{text}{_ANSI['reset']}"

    def echo(self, text: str = "") -> None:
        try:
            print(text)
        except Exception:
            try:
                sys.stdout.write(text + "\n")
                sys.stdout.flush()
            except Exception:
                pass


# ---------------------------------------------------------------------------- #
# Sample puml fixtures (inlined; zero filesystem deps)
# ---------------------------------------------------------------------------- #


_SIMPLE_PUML = "@startuml\nA -> B : hi\nB --> A : ok\n@enduml\n"

_CJK_PUML = (
    "@startuml\n"
    "title 中文标题\n"
    "用户 -> 服务 : 你好 こんにちは 안녕하세요\n"
    "服务 --> 用户 : ok\n"
    "@enduml\n"
)

_BAD_PUML = "@startuml\nA -> @@@ broken\n@enduml\n"


# ---------------------------------------------------------------------------- #
# Verification helpers (each one is a Case.func body)
# ---------------------------------------------------------------------------- #


def _v_python_floor() -> None:
    if sys.version_info < (3, 7):
        raise RuntimeError(
            "Python {} is below the supported floor (3.7+). pyplantuml-bundled "
            "targets the 3.7-3.14 envelope.".format(sys.version.split()[0])
        )


def _v_critical_stdlib() -> None:
    import importlib
    for mod in (
        "json", "re", "pathlib", "hashlib", "struct", "tempfile",
        "subprocess", "shutil", "io", "os", "sys", "time", "traceback",
        "platform",
    ):
        importlib.import_module(mod)


def _v_package_importable() -> None:
    import pyplantuml  # noqa: F401


def _v_pkg_dir_exists() -> None:
    import pyplantuml
    if not pyplantuml.PKG_DIR.is_dir():
        raise RuntimeError(
            "pyplantuml.PKG_DIR ({}) is not a directory.".format(pyplantuml.PKG_DIR)
        )


def _v_jar_exists() -> None:
    import pyplantuml
    if not pyplantuml.JAR_PATH.is_file():
        raise RuntimeError(
            "plantuml.jar missing at {}. The wheel did not ship the jar; "
            "the build pipeline likely skipped scripts/fetch_plantuml_jar.sh."
            .format(pyplantuml.JAR_PATH)
        )
    size = pyplantuml.JAR_PATH.stat().st_size
    if size < 5_000_000:  # real jar is ~22 MB
        raise RuntimeError(
            "plantuml.jar is implausibly small ({} bytes); expected ~22 MB."
            .format(size)
        )


def _v_jar_signature() -> None:
    """The jar must be a valid zip (jar files are zip)."""
    import zipfile
    import pyplantuml
    if not zipfile.is_zipfile(pyplantuml.JAR_PATH):
        raise RuntimeError(
            "plantuml.jar at {} is not a valid zip/jar archive."
            .format(pyplantuml.JAR_PATH)
        )


def _v_java_bin_exists() -> None:
    import pyplantuml
    if not pyplantuml.JAVA_BIN.is_file():
        raise RuntimeError(
            "bundled java executable missing at {}".format(pyplantuml.JAVA_BIN)
        )
    if os.name != "nt" and not os.access(pyplantuml.JAVA_BIN, os.X_OK):
        raise RuntimeError(
            "bundled java exists but is not executable: {} (mode={:o})".format(
                pyplantuml.JAVA_BIN,
                pyplantuml.JAVA_BIN.stat().st_mode,
            )
        )


def _v_java_runs() -> None:
    """`java -version` must exit 0 and print an OpenJDK / Java banner."""
    import pyplantuml
    proc = subprocess.run(
        [str(pyplantuml.JAVA_BIN), "-version"],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "java -version exited {}: stderr={!r}".format(
                proc.returncode, (proc.stderr or "")[:300]
            )
        )
    banner = (proc.stderr or "") + (proc.stdout or "")
    if "version" not in banner.lower():
        raise RuntimeError(
            "java -version printed no recognisable banner; got {!r}"
            .format(banner[:200])
        )


def _v_jre_module_set() -> None:
    """The bundled JRE must contain java.desktop / java.scripting / etc."""
    import pyplantuml
    proc = subprocess.run(
        [str(pyplantuml.JAVA_BIN), "--list-modules"],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "java --list-modules exited {}: {!r}".format(
                proc.returncode, (proc.stderr or "")[:200]
            )
        )
    text = proc.stdout or ""
    required = ("java.base", "java.desktop", "java.scripting", "java.xml")
    missing = [m for m in required if m not in text]
    if missing:
        raise RuntimeError(
            "jlink-stripped JRE is missing modules required by PlantUML: {}"
            .format(", ".join(missing))
        )


def _v_runtime_dir_layout() -> None:
    """On Linux: runtime/<plat>/{lib,fonts}; elsewhere: presence is optional."""
    import pyplantuml
    plat = pyplantuml._platform_key()
    runtime_dir = pyplantuml.PKG_DIR / "runtime" / plat
    if not plat.startswith("linux"):
        return  # macOS / Windows: no Linux-only runtime needed
    if not runtime_dir.is_dir():
        raise RuntimeError(
            "Linux runtime dir missing at {}; the wheel did not include the "
            "fontconfig + fonts payload.".format(runtime_dir)
        )
    for sub in ("lib", "fonts"):
        if not (runtime_dir / sub).is_dir():
            raise RuntimeError(
                "Linux runtime/{} subdirectory missing at {}".format(
                    sub, runtime_dir / sub
                )
            )


def _v_fontconfig_template() -> None:
    """fonts.conf.template must exist and contain placeholders."""
    import pyplantuml
    template = pyplantuml.PKG_DIR / "runtime" / "fonts.conf.template"
    if not template.is_file():
        raise RuntimeError("fonts.conf.template missing at {}".format(template))
    text = template.read_text(encoding="utf-8")
    for placeholder in ("{FONT_DIR}", "{CACHE_DIR}"):
        if placeholder not in text:
            raise RuntimeError(
                "fonts.conf.template lost placeholder {}; the build "
                "pipeline mangled the resource.".format(placeholder)
            )


def _v_linux_native_libs() -> None:
    """On Linux, libfontconfig.so.1 + libfreetype.so.6 must be staged."""
    import pyplantuml
    plat = pyplantuml._platform_key()
    if not plat.startswith("linux"):
        return
    lib = pyplantuml.PKG_DIR / "runtime" / plat / "lib"
    required = ("libfontconfig.so.1", "libfreetype.so.6")
    missing = [name for name in required if not (lib / name).is_file()]
    if missing:
        raise RuntimeError(
            "Linux runtime/lib is missing critical .so files: {}; "
            "stage_linux_runtime.sh did not run during build."
            .format(", ".join(missing))
        )


def _v_linux_fonts() -> None:
    """On Linux, DejaVuSans + WenQuanYi Micro Hei TTC must be staged."""
    import pyplantuml
    plat = pyplantuml._platform_key()
    if not plat.startswith("linux"):
        return
    fonts = pyplantuml.PKG_DIR / "runtime" / plat / "fonts"
    if not (fonts / "DejaVuSans.ttf").is_file():
        raise RuntimeError(
            "DejaVuSans.ttf not staged at {}; Latin/Cyrillic/Greek text "
            "will render as tofu inside slim containers.".format(fonts)
        )
    ttc = fonts / "wqy-microhei.ttc"
    if not ttc.is_file():
        raise RuntimeError(
            "wqy-microhei.ttc not staged at {}; CJK text will render as "
            "tofu inside slim containers.".format(fonts)
        )
    if ttc.stat().st_size < 1_000_000:
        raise RuntimeError(
            "wqy-microhei.ttc at {} is only {} bytes (expected ~5 MB); "
            "the build pipeline truncated it.".format(ttc, ttc.stat().st_size)
        )


def _v_cache_dir_writable() -> None:
    """The launcher must locate a writable cache dir for fonts.conf."""
    import pyplantuml
    cache = pyplantuml._cache_dir()
    if not cache.is_dir():
        raise RuntimeError(
            "_cache_dir() returned a non-directory: {}".format(cache)
        )
    probe = cache / ".selfcheck-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _v_version_call() -> None:
    """`pyplantuml.version()` must report PlantUML + JRE banners."""
    import pyplantuml
    out = pyplantuml.version()
    if "PlantUML" not in out:
        raise RuntimeError(
            "pyplantuml.version() did not contain 'PlantUML'; got first 200 "
            "chars: {!r}".format(out[:200])
        )
    if "OpenJDK" not in out and "Java" not in out:
        raise RuntimeError(
            "pyplantuml.version() did not contain a Java banner; got: {!r}"
            .format(out[:300])
        )


def _v_render_png() -> None:
    """Render a tiny puml to PNG and validate the magic bytes + size."""
    import pyplantuml
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "simple.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_SIMPLE_PUML)
        pyplantuml.render(src, output_dir=d, fmt="png")
        out = os.path.join(d, "simple.png")
        if not os.path.isfile(out):
            raise RuntimeError("PNG output not produced at {}".format(out))
        with open(out, "rb") as f:
            head = f.read(8)
        if head != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError(
                "Output at {} is not a PNG (magic bytes: {!r}).".format(out, head)
            )
        size = os.path.getsize(out)
        if size < 500:
            raise RuntimeError(
                "PNG at {} is implausibly small ({} bytes).".format(out, size)
            )


def _v_render_svg() -> None:
    """Render to SVG and ensure the result is recognisable XML+SVG."""
    import pyplantuml
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "simple.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_SIMPLE_PUML)
        pyplantuml.render(src, output_dir=d, fmt="svg")
        out = os.path.join(d, "simple.svg")
        text = open(out, "r", encoding="utf-8").read()
        if "<svg " not in text:
            raise RuntimeError(
                "SVG output at {} missing <svg> tag; first 200 chars: {!r}"
                .format(out, text[:200])
            )


def _v_checkonly_valid() -> None:
    """A valid puml must pass `-checkonly`."""
    import pyplantuml
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "good.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_SIMPLE_PUML)
        if not pyplantuml.check(src):
            raise RuntimeError("`check()` rejected a valid puml file.")


def _v_checkonly_rejects_bad() -> None:
    """A malformed puml must fail `-checkonly`."""
    import pyplantuml
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "bad.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_BAD_PUML)
        if pyplantuml.check(src):
            raise RuntimeError("`check()` accepted a malformed puml file.")


def _v_cjk_render_visual_proxy() -> None:
    """
    Render a CJK puml; assert PNG byte size + dimensions are above the
    tofu threshold. Tofu glyphs do not raise, so byte-size and width
    are how we catch font-stack regressions.
    """
    import pyplantuml
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "cjk.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_CJK_PUML)
        pyplantuml.render(src, output_dir=d, fmt="png")
        png = os.path.join(d, "cjk.png")
        size = os.path.getsize(png)
        if size < 4_000:
            raise RuntimeError(
                "CJK PNG at {} is suspiciously small ({} bytes); a tofu "
                "render compresses much smaller than real glyph data."
                .format(png, size)
            )
        # Read width/height from PNG header (no Pillow dep).
        with open(png, "rb") as f:
            f.read(16)  # magic + IHDR length + type
            ihdr = f.read(8)
        width, height = struct.unpack(">II", ihdr)
        if width < 200 or height < 60:
            raise RuntimeError(
                "CJK PNG too small ({}x{}); tofu glyphs collapse to zero "
                "advance and shrink the layout.".format(width, height)
            )


def _v_cjk_svg_entities() -> None:
    """SVG output of a CJK puml must contain numeric character entities."""
    import pyplantuml
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "cjk.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_CJK_PUML)
        pyplantuml.render(src, output_dir=d, fmt="svg")
        text = open(os.path.join(d, "cjk.svg"), "r", encoding="utf-8").read()
        if "&#20013;" not in text:  # 中
            raise RuntimeError(
                "SVG output missing CJK character entity '&#20013;' (中). "
                "PlantUML emits CJK as numeric XML entities."
            )


def _v_render_offline() -> None:
    """
    Render a puml with all common HTTP proxy variables blocked. PlantUML
    does NOT need network for local diagrams, but a regression here would
    surface as a hang in air-gapped CI.
    """
    import pyplantuml
    blocked = {
        "http_proxy": "http://127.0.0.1:1",
        "https_proxy": "http://127.0.0.1:1",
        "HTTP_PROXY": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "no_proxy": "",
    }
    with tempfile.TemporaryDirectory(prefix="pyplantuml-selfcheck-") as d:
        src = os.path.join(d, "offline.puml")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_SIMPLE_PUML)
        pyplantuml.render(src, output_dir=d, fmt="png", extra_args=())
        # Re-run with blocked proxies via run() to pass env override.
        pyplantuml.run(
            ["-tpng", "-o", d, src],
            env=blocked, check=True, timeout=30,
        )
        if not os.path.isfile(os.path.join(d, "offline.png")):
            raise RuntimeError("offline render produced no PNG.")


def _v_run_passthrough() -> None:
    """`pyplantuml.run(['-help'], capture_output=True)` must not raise."""
    import pyplantuml
    proc = pyplantuml.run(["-help"], capture_output=True, check=False, timeout=20)
    blob = (proc.stdout or "") + (proc.stderr or "")
    if "Usage" not in blob and "plantuml" not in blob.lower():
        raise RuntimeError(
            "plantuml -help printed nothing recognisable; first 200 chars: {!r}"
            .format(blob[:200])
        )


_TTF_MAGICS = (
    b"\x00\x01\x00\x00",  # TrueType
    b"OTTO",              # OpenType (CFF)
    b"true",              # Apple TrueType
    b"typ1",              # Apple Type 1
)
_TTC_MAGIC = b"ttcf"  # TrueType Collection


def _v_font_signatures() -> None:
    """Read the first 4 bytes of every staged font and verify the magic.

    Catches a build-pipeline regression where a font got truncated or
    silently replaced with HTML (e.g. an upstream mirror returned a
    rate-limit page instead of the .ttc).
    """
    import pyplantuml
    plat = pyplantuml._platform_key()
    if not plat.startswith("linux"):
        return
    fonts = pyplantuml.PKG_DIR / "runtime" / plat / "fonts"
    bad: List[str] = []
    for ttf in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        p = fonts / ttf
        if not p.is_file():
            bad.append("{} missing".format(ttf))
            continue
        with open(p, "rb") as f:
            head = f.read(4)
        if head not in _TTF_MAGICS:
            bad.append("{} has unexpected magic {!r}".format(ttf, head))
    ttc = fonts / "wqy-microhei.ttc"
    if ttc.is_file():
        with open(ttc, "rb") as f:
            head = f.read(4)
        if head != _TTC_MAGIC:
            bad.append("wqy-microhei.ttc has unexpected magic {!r}".format(head))
    if bad:
        raise RuntimeError("font signature mismatches: " + "; ".join(bad))


def _is_musl() -> bool:
    """True iff the running interpreter is on a musl-based Linux."""
    if not sys.platform.startswith("linux"):
        return False
    for p in ("/lib/ld-musl-x86_64.so.1", "/lib/ld-musl-aarch64.so.1",
              "/lib/ld-musl-armhf.so.1"):
        if os.path.exists(p):
            return True
    try:
        libc, _ = platform.libc_ver()
        return libc == ""
    except Exception:
        return False


def _v_libfontconfig_loadable() -> None:
    """ctypes-load libfontconfig.so.1 from the staged path; verify a known
    symbol is exported.

    Pre-loads the dependency .so files in order so dlopen's DT_NEEDED
    resolution finds them without relying on LD_LIBRARY_PATH (which is
    only set inside ``pyplantuml.run`` calls, not during selfcheck).

    Skipped on musl: musl's ld.so does not honour RTLD_GLOBAL for
    sibling DT_NEEDED resolution the way glibc does, so each dlopen
    re-walks the file search path. The JRE rendering tests below
    already exercise the same .so chain end-to-end via subprocess +
    LD_LIBRARY_PATH, so this in-process probe is redundant on musl.
    """
    import ctypes
    import pyplantuml
    plat = pyplantuml._platform_key()
    if not plat.startswith("linux"):
        return
    if _is_musl():
        return
    lib = pyplantuml.PKG_DIR / "runtime" / plat / "lib"
    # Load deps first so ld.so already has them when libfontconfig wants them.
    for sub in (
        "libbrotlicommon.so.1", "libbrotlidec.so.1",
        "libpng16.so.16", "libexpat.so.1",
        "libuuid.so.1", "libz.so.1",
        "libfreetype.so.6",
    ):
        p = lib / sub
        if p.is_file():
            try:
                ctypes.CDLL(str(p), mode=ctypes.RTLD_GLOBAL)
            except OSError as exc:
                raise RuntimeError(
                    "Failed to dlopen dependency {}: {}".format(sub, exc)
                ) from exc
    handle = ctypes.CDLL(str(lib / "libfontconfig.so.1"))
    init_fn = getattr(handle, "FcInit", None)
    if init_fn is None:
        raise RuntimeError(
            "libfontconfig.so.1 loaded but FcInit symbol not found — "
            "the .so may have been stripped beyond what we expect."
        )
    init_fn.restype = ctypes.c_int
    if init_fn() == 0:
        raise RuntimeError("FcInit() returned 0 (failure).")


def _v_libfreetype_loadable() -> None:
    """ctypes-load libfreetype.so.6 and call FT_Init_FreeType.

    libfreetype.so.6's DT_NEEDED list pulls in libpng16 / libz / libbrotlidec.
    ld.so does not look in our staged dir by default, so we preload deps
    by absolute path before opening libfreetype itself.  Skipped on musl
    for the same reason _v_libfontconfig_loadable is."""
    import ctypes
    import pyplantuml
    plat = pyplantuml._platform_key()
    if not plat.startswith("linux"):
        return
    if _is_musl():
        return
    lib = pyplantuml.PKG_DIR / "runtime" / plat / "lib"
    for sub in (
        "libbrotlicommon.so.1", "libbrotlidec.so.1",
        "libpng16.so.16", "libz.so.1",
    ):
        p = lib / sub
        if p.is_file():
            try:
                ctypes.CDLL(str(p), mode=ctypes.RTLD_GLOBAL)
            except OSError as exc:
                raise RuntimeError(
                    "Failed to dlopen freetype dependency {}: {}".format(sub, exc)
                ) from exc
    handle = ctypes.CDLL(str(lib / "libfreetype.so.6"))
    init_fn = getattr(handle, "FT_Init_FreeType", None)
    if init_fn is None:
        raise RuntimeError(
            "libfreetype.so.6 loaded but FT_Init_FreeType not found."
        )
    init_fn.restype = ctypes.c_int
    init_fn.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    library_ptr = ctypes.c_void_p()
    rc = init_fn(ctypes.byref(library_ptr))
    if rc != 0:
        raise RuntimeError("FT_Init_FreeType returned {} (non-zero = error).".format(rc))


def _v_dep_click() -> None:
    """``click`` must import and behave for the most basic command."""
    import click
    from click.testing import CliRunner
    if not hasattr(click, "command"):
        raise RuntimeError(
            "click imported but lacks click.command — installed package may be "
            "shadowed by something else on sys.path."
        )

    @click.command()
    @click.option("--n", default=2, type=int)
    def _stub(n):  # pragma: no cover - exercised via CliRunner below
        click.echo("ok={}".format(n * 2))

    res = CliRunner().invoke(_stub, ["--n", "3"])
    if res.exit_code != 0:
        raise RuntimeError(
            "click.CliRunner stub exited {}; output={!r}".format(
                res.exit_code, res.output
            )
        )
    if "ok=6" not in res.output:
        raise RuntimeError(
            "click stub produced unexpected output: {!r}".format(res.output)
        )


def _v_pyinstaller_resources() -> None:
    """When running from a PyInstaller frozen exe, _MEIPASS must exist
    and the bundled assets must live under <_MEIPASS>/pyplantuml."""
    if not getattr(sys, "frozen", False):
        return  # not frozen — nothing to assert here
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass or not os.path.isdir(meipass):
        raise RuntimeError(
            "Running frozen but sys._MEIPASS={!r} is not a directory."
            .format(meipass)
        )
    expected = os.path.join(meipass, "pyplantuml", "plantuml.jar")
    if not os.path.isfile(expected):
        raise RuntimeError(
            "Frozen exe did not bundle plantuml.jar at expected path {}. "
            "PyInstaller spec datas= entry is missing or wrong."
            .format(expected)
        )


# ---------------------------------------------------------------------------- #
# Environment dump
# ---------------------------------------------------------------------------- #


def _safe(fn) -> str:
    try:
        v = fn()
    except BaseException as exc:
        return "(unavailable: {}: {})".format(type(exc).__name__, exc)
    if v is None:
        return "(none)"
    return v if isinstance(v, str) else str(v)


def _collect_env() -> List[Tuple[str, List[Tuple[str, str]]]]:
    sections: List[Tuple[str, List[Tuple[str, str]]]] = []

    py = []
    py.append(("implementation", _safe(platform.python_implementation)))
    py.append(("version", _safe(lambda: sys.version.split()[0])))
    py.append(("build", _safe(lambda: " / ".join(platform.python_build()))))
    py.append(("compiler", _safe(platform.python_compiler)))
    py.append(("executable", _safe(lambda: sys.executable)))
    py.append(("prefix", _safe(lambda: sys.prefix)))
    py.append(("byteorder", _safe(lambda: sys.byteorder)))
    py.append(("maxsize bits", _safe(lambda: 64 if sys.maxsize > (1 << 32) else 32)))
    sections.append(("Python interpreter", py))

    osr = []
    osr.append(("system", _safe(platform.system)))
    osr.append(("release", _safe(platform.release)))
    osr.append(("version", _safe(platform.version)))
    osr.append(("machine", _safe(platform.machine)))
    osr.append(("processor", _safe(lambda: platform.processor() or "(unknown)")))
    osr.append(("platform", _safe(platform.platform)))
    if sys.platform.startswith("linux"):
        osr.append(("libc", _safe(
            lambda: " ".join(s for s in platform.libc_ver() if s) or "(unknown)"
        )))
    elif sys.platform == "darwin":
        osr.append(("mac_ver", _safe(
            lambda: " ".join(s for s in platform.mac_ver() if s) or "(unknown)"
        )))
    elif sys.platform == "win32":
        osr.append(("win32_ver", _safe(
            lambda: " ".join(s for s in platform.win32_ver() if s) or "(unknown)"
        )))
    sections.append(("OS / platform", osr))

    proc = []
    proc.append(("pid", _safe(os.getpid)))
    proc.append(("cwd", _safe(os.getcwd)))
    if hasattr(os, "getuid"):
        proc.append(("uid/gid", _safe(lambda: "{}/{}".format(os.getuid(), os.getgid()))))
    proc.append(("argv[0]", _safe(lambda: sys.argv[0] if sys.argv else "(none)")))
    proc.append(("stdin tty?", _safe(lambda: bool(sys.stdin and sys.stdin.isatty()))))
    proc.append(("stdout tty?", _safe(lambda: bool(sys.stdout and sys.stdout.isatty()))))
    sections.append(("Process", proc))

    loc = []

    def _enc():
        import locale
        return locale.getpreferredencoding(False)

    def _locale():
        import locale
        parts = [p for p in locale.getlocale() if p]
        return " / ".join(parts) if parts else "(C)"

    loc.append(("preferred encoding", _safe(_enc)))
    loc.append(("locale", _safe(_locale)))
    loc.append(("stdout encoding", _safe(lambda: getattr(sys.stdout, "encoding", "(none)"))))
    loc.append(("filesystem encoding", _safe(sys.getfilesystemencoding)))
    loc.append(("LC_ALL", _safe(lambda: os.environ.get("LC_ALL", "(unset)"))))
    loc.append(("LANG", _safe(lambda: os.environ.get("LANG", "(unset)"))))
    sections.append(("Locale / encoding", loc))

    relevant = (
        "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH", "PYTHONHOME",
        "PYTHONIOENCODING", "TERM", "COLORTERM", "TZ", "DISPLAY",
        "HOME", "USER", "LOGNAME", "SHELL",
        "USERPROFILE", "USERNAME", "APPDATA", "LOCALAPPDATA", "COMSPEC",
        "TMPDIR", "TEMP", "TMP",
        "JAVA_HOME", "PYPLANTUML_JAVA",
        "LD_LIBRARY_PATH", "FONTCONFIG_FILE", "FONTCONFIG_PATH",
        "CI", "GITHUB_ACTIONS", "RUNNER_OS",
    )
    env_rows = [(k, _safe(lambda v=k: os.environ.get(v, "(unset)"))) for k in relevant]

    def _path_preview() -> str:
        path = os.environ.get("PATH", "")
        parts = path.split(os.pathsep)
        if len(parts) <= 3:
            return path or "(unset)"
        return os.pathsep.join(parts[:3]) + "  (... {} more entries)".format(len(parts) - 3)

    env_rows.append(("PATH (head)", _safe(_path_preview)))
    sections.append(("Environment variables", env_rows))

    t = []
    t.append(("UTC now", _safe(lambda: datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds").replace("+00:00", "Z"))))
    t.append(("tzname", _safe(lambda: " / ".join(time.tzname))))
    sections.append(("Time", t))

    fr = []
    fr.append(("frozen", _safe(lambda: getattr(sys, "frozen", False))))
    fr.append(("_MEIPASS", _safe(
        lambda: getattr(sys, "_MEIPASS", "(not running under PyInstaller)")
    )))
    sections.append(("Frozen / PyInstaller", fr))

    pkg = []

    def _pkg_version() -> str:
        import pyplantuml
        return getattr(pyplantuml, "__version__", "(unknown)")

    def _pkg_dir() -> str:
        import pyplantuml
        return str(pyplantuml.PKG_DIR)

    def _jar_path() -> str:
        import pyplantuml
        return "{} ({} bytes)".format(
            pyplantuml.JAR_PATH,
            pyplantuml.JAR_PATH.stat().st_size if pyplantuml.JAR_PATH.exists() else "missing",
        )

    def _java_bin() -> str:
        import pyplantuml
        return str(pyplantuml.JAVA_BIN)

    def _platform_key() -> str:
        import pyplantuml
        return pyplantuml._platform_key()

    pkg.append(("version", _safe(_pkg_version)))
    pkg.append(("install path", _safe(_pkg_dir)))
    pkg.append(("plantuml.jar", _safe(_jar_path)))
    pkg.append(("bundled java", _safe(_java_bin)))
    pkg.append(("platform key", _safe(_platform_key)))
    sections.append(("pyplantuml package", pkg))

    return sections


# ---------------------------------------------------------------------------- #
# Case registry
# ---------------------------------------------------------------------------- #


def _build_groups() -> List[Tuple[str, List[Case]]]:
    return [
        ("Python runtime", [
            Case("python_floor", "sys.version_info >= (3, 7)", _v_python_floor,
                 "Upgrade Python to 3.7+ (we test 3.7-3.14 in CI)."),
            Case("critical_stdlib", "import json/re/pathlib/...",
                 _v_critical_stdlib,
                 "Stdlib looks broken — re-install or rebuild your interpreter."),
        ]),
        ("Python dependencies", [
            Case("dep_click", "import click + invoke a stub command via CliRunner",
                 _v_dep_click,
                 "pip install --force-reinstall click  (or rebuild the wheel)."),
        ]),
        ("Package layout", [
            Case("pkg_importable", "import pyplantuml", _v_package_importable,
                 "pip install --force-reinstall pyplantuml-bundled"),
            Case("pkg_dir_resolves", "PKG_DIR is a directory", _v_pkg_dir_exists,
                 "Reinstall: the package directory is missing."),
            Case("jar_present", "plantuml.jar bundled in the wheel",
                 _v_jar_exists,
                 "Reinstall: the wheel skipped scripts/fetch_plantuml_jar.sh."),
            Case("jar_zip_signature", "plantuml.jar is a valid jar/zip",
                 _v_jar_signature,
                 "Reinstall: plantuml.jar appears truncated or corrupted."),
            Case("java_bin_present", "bundled jre/bin/java exists + executable",
                 _v_java_bin_exists,
                 "Wheel built for the wrong platform; install the right tag, "
                 "or set PYPLANTUML_JAVA to a system Java."),
            Case("jre_module_set", "java --list-modules has java.desktop / java.scripting",
                 _v_jre_module_set,
                 "jlink stripped too aggressively; rebuild with the full module set."),
            Case("runtime_dir_layout", "runtime/<plat>/{lib,fonts} (Linux only)",
                 _v_runtime_dir_layout,
                 "Run scripts/stage_linux_runtime.sh inside the build container."),
            Case("fontconfig_template", "runtime/fonts.conf.template intact",
                 _v_fontconfig_template,
                 "fonts.conf.template was mangled; reinstall the wheel."),
            Case("linux_native_libs", "libfontconfig.so.1 + libfreetype.so.6 staged",
                 _v_linux_native_libs,
                 "Wheel was built without stage_linux_runtime.sh; reinstall."),
            Case("linux_fonts", "DejaVu + WenQuanYi MicroHei TTC staged",
                 _v_linux_fonts,
                 "Wheel was built without vendored fonts; reinstall."),
        ]),
        ("Bundled native libraries (Linux)", [
            Case("libfontconfig_loadable",
                 "ctypes.CDLL(libfontconfig.so.1) + FcInit() returns success",
                 _v_libfontconfig_loadable,
                 "libfontconfig.so.1 staged but unloadable — likely an ABI "
                 "mismatch; rebuild inside the matching manylinux/musllinux "
                 "container."),
            Case("libfreetype_loadable",
                 "ctypes.CDLL(libfreetype.so.6) + FT_Init_FreeType returns 0",
                 _v_libfreetype_loadable,
                 "libfreetype.so.6 staged but unloadable — same ABI mismatch "
                 "diagnosis as libfontconfig."),
        ]),
        ("Bundled font assets (Linux)", [
            Case("font_signatures",
                 "TTF magic for DejaVu + 'ttcf' for WenQuanYi MicroHei",
                 _v_font_signatures,
                 "Font file truncated or replaced with HTML during build "
                 "(common when an upstream mirror rate-limited the download). "
                 "Rebuild the wheel."),
        ]),
        ("Runtime probes", [
            Case("java_runs", "java -version exits 0 and prints a banner",
                 _v_java_runs,
                 "Bundled java cannot run on this OS/arch; verify the wheel "
                 "platform tag matches your machine."),
            Case("cache_dir_writable", "fontconfig cache dir is writable",
                 _v_cache_dir_writable,
                 "All cache candidates are read-only; set XDG_CACHE_HOME or "
                 "TMPDIR to a writable directory."),
            Case("version_call", "pyplantuml.version() banner",
                 _v_version_call,
                 "plantuml.jar started but did not print its banner — likely "
                 "an incompatible JRE."),
        ]),
        ("Rendering paths", [
            Case("render_png", "render(simple.puml, fmt=png) → PNG magic bytes",
                 _v_render_png,
                 "Cannot render PNG; check the previous case for the root cause."),
            Case("render_svg", "render(simple.puml, fmt=svg) → contains <svg>",
                 _v_render_svg,
                 "Cannot render SVG; same diagnostics path as PNG."),
            Case("checkonly_valid", "check(good.puml) → True",
                 _v_checkonly_valid,
                 "Static checker rejected a known-good puml; PlantUML upstream "
                 "regression?"),
            Case("checkonly_rejects_bad", "check(bad.puml) → False",
                 _v_checkonly_rejects_bad,
                 "Static checker accepted obviously broken syntax; PlantUML "
                 "upstream regression?"),
            Case("run_passthrough", "run(['-help']) prints usage banner",
                 _v_run_passthrough,
                 "plantuml.jar -help did not print a banner; jar is corrupted."),
        ]),
        ("CJK rendering (visual proxy)", [
            Case("cjk_png_size", "CJK PNG byte size > 4 KB AND width > 200 px",
                 _v_cjk_render_visual_proxy,
                 "CJK appears as tofu (square boxes); the font subsystem is "
                 "missing. On Linux, ensure runtime/<plat>/{lib,fonts} are "
                 "staged in the wheel."),
            Case("cjk_svg_entities", "SVG contains '&#20013;' for 中",
                 _v_cjk_svg_entities,
                 "CJK character entities missing from SVG; font fallback "
                 "is broken."),
        ]),
        ("Network independence", [
            Case("render_offline", "render with all *_proxy = 127.0.0.1:1",
                 _v_render_offline,
                 "Rendering tried to reach the network — should be impossible "
                 "for local diagrams. Check for an unintended -DPLANTUML_LIMIT "
                 "or remote include."),
        ]),
        ("Frozen / PyInstaller", [
            Case("pyinstaller_resources", "_MEIPASS layout (only when frozen)",
                 _v_pyinstaller_resources,
                 "Frozen build is missing bundled resources; check spec datas=."),
        ]),
    ]


# ---------------------------------------------------------------------------- #
# Output formatters
# ---------------------------------------------------------------------------- #


def _format_traceback(tb_text: str, max_frames: int = 5) -> List[str]:
    lines = (tb_text or "").rstrip().splitlines()
    if not lines:
        return ["(no traceback captured)"]
    if len(lines) <= max_frames * 2 + 2:
        return lines
    head = lines[:1]
    tail = lines[-(max_frames * 2 + 1):]
    return head + ["... <{} earlier frames trimmed>".format(
        len(lines) - len(head) - len(tail)
    )] + tail


def _print_env(painter: _Painter) -> None:
    try:
        sections = _collect_env()
    except BaseException as exc:
        painter.echo(painter.style(
            "(env introspection failed: {}; continuing)".format(exc),
            fg="yellow",
        ))
        return
    for label, rows in sections:
        painter.echo(painter.style(label, fg="cyan", bold=True))
        if not rows:
            painter.echo("  (no facts)")
            painter.echo("")
            continue
        width = max(len(k) for k, _ in rows)
        for k, v in rows:
            key = painter.style(k.ljust(width), fg="white", bold=True)
            if v.startswith("(unavailable"):
                v_styled = painter.style(v, fg="yellow")
            elif v in {"(unset)", "(none)", "(unknown)"}:
                v_styled = painter.style(v, dim=True)
            else:
                v_styled = v
            painter.echo("  " + key + " : " + v_styled)
        painter.echo("")


def _print_pass(painter: _Painter, r: Result) -> None:
    tag = painter.style("[PASS]", fg="green", bold=True)
    name = painter.style(r.case.name, fg="white", bold=True)
    painter.echo("  {} {} :: {} ({:.1f} ms)".format(tag, name, r.case.method, r.elapsed_ms))


def _print_fail(painter: _Painter, r: Result) -> None:
    tag = painter.style("[FAIL]", fg="red", bold=True)
    name = painter.style(r.case.name, fg="white", bold=True)
    painter.echo("  {} {} :: {} ({:.1f} ms)".format(tag, name, r.case.method, r.elapsed_ms))
    label = painter.style("        ↳", fg="red")
    if r.error is not None:
        cat = painter.style(type(r.error).__name__, fg="yellow", bold=True)
        msg = painter.style(str(r.error) or "(no error message)", fg="yellow")
        painter.echo("{} category: {}".format(label, cat))
        painter.echo("{} message:  {}".format(label, msg))
    if r.traceback_text:
        painter.echo("{} traceback (most actionable frames):".format(label))
        for line in _format_traceback(r.traceback_text):
            painter.echo("           " + line)
    if r.case.remediation:
        painter.echo("{} remediation: {}".format(
            label, painter.style(r.case.remediation, fg="green")
        ))


def _print_summary(painter: _Painter, results: List[Result], elapsed: float) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = total - passed
    bar = painter.style("=" * 70, fg="cyan", dim=True)
    painter.echo("")
    painter.echo(bar)
    if failed == 0:
        painter.echo(
            painter.style("Selfcheck summary: ", fg="cyan", bold=True)
            + painter.style("{} PASS".format(passed), fg="green", bold=True)
            + " (out of {}, {:.2f}s wall)".format(total, elapsed)
        )
        painter.echo(painter.style(
            "All checks passed — this install can render PlantUML diagrams "
            "without any extra setup.",
            fg="green",
        ))
    else:
        painter.echo(
            painter.style("Selfcheck summary: ", fg="cyan", bold=True)
            + painter.style("{} PASS".format(passed), fg="green", bold=True)
            + ", "
            + painter.style("{} FAIL".format(failed), fg="red", bold=True)
            + " (out of {}, {:.2f}s wall)".format(total, elapsed)
        )
        painter.echo(painter.style("Failed cases:", fg="red", bold=True))
        for r in results:
            if r.status == "FAIL":
                err = str(r.error) if r.error else "(no error)"
                painter.echo(
                    "  - "
                    + painter.style(r.case.name, fg="red", bold=True)
                    + ": "
                    + err
                )
    painter.echo(bar)


# ---------------------------------------------------------------------------- #
# Public runner
# ---------------------------------------------------------------------------- #


def _run_one(case: Case) -> Result:
    started = time.time()
    try:
        case.func()
    except BaseException as exc:
        return Result(
            case=case, status="FAIL",
            elapsed_ms=(time.time() - started) * 1000,
            error=exc,
            traceback_text=traceback.format_exc(),
        )
    return Result(case=case, status="PASS", elapsed_ms=(time.time() - started) * 1000)


def run_selfcheck(argv: Optional[Sequence[str]] = None) -> int:
    """
    Run every registered self-check case and print a structured PASS/FAIL
    report on stdout. Returns the count of failed cases (0 when clean).

    Honoured argv flags:

    * ``--no-color``   force disable ANSI colour
    * ``--color``      force enable ANSI colour even when stdout is not a TTY
    * ``--no-env``     skip the environment dump (faster, less output)
    """
    args = list(argv or [])
    force_color: Optional[bool] = None
    skip_env = False
    for a in args:
        if a == "--no-color":
            force_color = False
        elif a == "--color":
            force_color = True
        elif a == "--no-env":
            skip_env = True
        # ignore unknown flags rather than crash

    painter = _Painter(force_color=force_color)
    bar = painter.style("=" * 70, fg="cyan", dim=True)
    painter.echo(bar)
    painter.echo(painter.style("plantuml selfcheck", fg="cyan", bold=True))
    painter.echo(bar)
    painter.echo("")

    if not skip_env:
        try:
            _print_env(painter)
        except BaseException:
            painter.echo("(env introspection failed; continuing)")
            painter.echo("")

    try:
        groups = _build_groups()
    except BaseException as exc:
        painter.echo(painter.style(
            "Catastrophic: selfcheck failed to assemble its case list: {!r}".format(exc),
            fg="red", bold=True,
        ))
        return 1

    started = time.time()
    all_results: List[Result] = []
    for label, cases in groups:
        painter.echo(
            painter.style("|", fg="cyan", bold=True) + " "
            + painter.style(label, fg="cyan", bold=True)
        )
        for case in cases:
            r = _run_one(case)
            (_print_pass if r.status == "PASS" else _print_fail)(painter, r)
            all_results.append(r)
        painter.echo("")
    elapsed = time.time() - started
    _print_summary(painter, all_results, elapsed)
    return sum(1 for r in all_results if r.status == "FAIL")
