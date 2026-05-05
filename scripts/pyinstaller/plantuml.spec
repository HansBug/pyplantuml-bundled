# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ``plantuml`` portable executable.

Two output flavours:
  * ``onefile`` — a single self-extracting binary. Cold-start cost is
    higher (PyInstaller unpacks _MEIPASS to a tempdir on every launch)
    but distribution is one file.
  * ``onedir``  — a directory next to the binary; we also zip it for
    distribution. Cold start is fast because resources are already on
    disk; the binary itself is tiny.

Driven by the env var ``PYI_FLAVOUR``: ``onefile`` (default) or ``onedir``.

Resources to bundle:
  * the entire ``src/pyplantuml/`` package directory under ``pyplantuml/``
    so ``sys._MEIPASS / 'pyplantuml' / …`` resolves identically to the
    pip-installed layout.

Hidden imports:
  * ``click`` (and ``click.testing`` because the selfcheck stubs it)
"""
import os
import sys
from pathlib import Path

block_cipher = None

flavour = os.environ.get("PYI_FLAVOUR", "onefile").strip().lower()
assert flavour in ("onefile", "onedir"), f"PYI_FLAVOUR must be onefile|onedir, got {flavour!r}"

# Paths anchored to the spec file (one level deeper than the repo root).
SPEC_DIR = Path(SPECPATH).resolve()        # noqa: F821 - injected by PyInstaller
ROOT = SPEC_DIR.parent.parent              # repo root
SRC_PKG = ROOT / "src" / "pyplantuml"
ENTRY = SPEC_DIR / "entry.py"

# We want every file under src/pyplantuml/ — Python sources, plantuml.jar,
# the entire jre/, the runtime/ tree — to land under <_MEIPASS>/pyplantuml/.
# Walk the tree and split: shared-library binaries (.so / .dylib / .dll)
# go into PyInstaller's `binaries` list so its ctypes hook lets the
# launcher dlopen them at runtime; everything else (jar, fonts, scripts,
# *.conf templates, etc.) goes into `datas`.
_BINARY_SUFFIXES = (".so", ".dylib", ".dll", ".jnilib")

datas = []
binaries = []
for path in SRC_PKG.rglob("*"):
    if not path.is_file():
        continue
    rel_dir = path.parent.relative_to(SRC_PKG)
    target = "pyplantuml" if str(rel_dir) == "." else str(Path("pyplantuml") / rel_dir)
    name = path.name
    is_binary = any(name.endswith(suf) for suf in _BINARY_SUFFIXES) or ".so." in name
    (binaries if is_binary else datas).append((str(path), target))

hiddenimports = [
    "click",
    "click.testing",
    "pyplantuml",
    "pyplantuml.diagnostics",
    "pyplantuml._click_cli",
    # stdlib modules our diagnostics smoke-tests load via importlib so
    # PyInstaller's static analysis can't see them otherwise:
    "json", "re", "pathlib", "hashlib", "struct", "tempfile",
    "subprocess", "shutil", "io", "os", "sys", "time", "traceback",
    "platform", "ctypes", "zipfile", "datetime", "locale",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the binary lean: we never need a GUI here.
        "tkinter", "test", "tests", "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

EXE_NAME = "plantuml"

# macOS only: tell PyInstaller to ad-hoc sign every bundled binary
# AND embed our JIT-allowing entitlements file at sign time, so the
# JVM's PROT_EXEC mmap() succeeds on Apple Silicon.
_macos_entitlements = str(SPEC_DIR / "entitlements.plist") if sys.platform == "darwin" else None
_macos_codesign_identity = "-" if sys.platform == "darwin" else None

if flavour == "onefile":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name=EXE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=_macos_codesign_identity,
        entitlements_file=_macos_entitlements,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=EXE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        codesign_identity=_macos_codesign_identity,
        entitlements_file=_macos_entitlements,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=EXE_NAME,
    )
