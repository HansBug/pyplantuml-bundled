#!/usr/bin/env bash
# Build both onefile and onedir+zip flavours of the portable plantuml exe.
#
# Inputs (must already exist; usually produced by the wheel-build pipeline):
#   src/pyplantuml/plantuml.jar
#   src/pyplantuml/jre/
#   src/pyplantuml/runtime/<linux-arch>/  (only on Linux)
#
# Outputs:
#   pyinstaller-dist/plantuml-onefile-<plat>            (single binary)
#   pyinstaller-dist/plantuml-onedir-<plat>.zip         (zipped onedir)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PLAT_TAG="${PYI_PLAT_TAG:-$(python -c 'import platform,sys; s=platform.system().lower(); m=platform.machine().lower(); m={"amd64":"x86_64","x86_64":"x86_64","aarch64":"aarch64","arm64":"aarch64"}.get(m,m); print({"linux":"linux","darwin":"macos","windows":"windows"}.get(s,s)+"-"+m)')}"
EXE_SUFFIX=""
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) EXE_SUFFIX=".exe" ;;
esac
case "${OS:-}" in
    Windows_NT) EXE_SUFFIX=".exe" ;;
esac

OUT="$ROOT/pyinstaller-dist"
WORK="$ROOT/pyinstaller-build"
mkdir -p "$OUT"
rm -rf "$WORK"

# Make sure assets are present.
test -f src/pyplantuml/plantuml.jar || { echo "FATAL: src/pyplantuml/plantuml.jar missing"; exit 1; }
test -d src/pyplantuml/jre          || { echo "FATAL: src/pyplantuml/jre/ missing"; exit 1; }

# macOS: ad-hoc codesign every JRE dylib + executable BEFORE PyInstaller
# bundles them.  Crucially we DO NOT use --options runtime here, because
# hardened-runtime on Apple Silicon refuses the JVM's mmap(PROT_EXEC)
# even when JIT is disabled (init-time codecache reservation still
# triggers it).  Plain ad-hoc signing keeps the dylibs loadable but
# leaves the runtime mode permissive enough for the JVM to start.
if [[ "$(uname -s)" = "Darwin" ]]; then
    echo "==> ad-hoc codesigning bundled JRE before PyInstaller"
    find src/pyplantuml/jre -type f \
        \( -perm -u+x -o -name '*.dylib' -o -name '*.jnilib' \) \
        -exec codesign --force --sign - --timestamp=none {} \; 2>/dev/null || true
fi

run_pyi() {
    local flavour="$1"
    rm -rf "$ROOT/build" "$ROOT/dist"
    PYI_FLAVOUR="$flavour" pyinstaller \
        --noconfirm \
        --clean \
        --workpath "$WORK/$flavour" \
        --distpath "$ROOT/dist" \
        scripts/pyinstaller/plantuml.spec
}

# ---- onefile -----------------------------------------------------------
echo "==> building onefile flavour for $PLAT_TAG"
run_pyi onefile
ONEFILE_NAME="plantuml-onefile-${PLAT_TAG}${EXE_SUFFIX}"
cp "$ROOT/dist/plantuml${EXE_SUFFIX}" "$OUT/$ONEFILE_NAME"
chmod +x "$OUT/$ONEFILE_NAME" || true

# macOS: PyInstaller already signed everything via the spec
# (codesign_identity='-' + entitlements_file=...). Verify the
# entitlements landed instead of resigning blindly.
if [[ "$(uname -s)" = "Darwin" ]]; then
    codesign -d --entitlements - "$OUT/$ONEFILE_NAME" 2>&1 | grep -E 'allow-jit|disable-library-validation' \
        || echo "WARN: onefile binary missing JIT entitlements"
fi

ls -lh "$OUT/$ONEFILE_NAME"

# ---- onedir + zip ------------------------------------------------------
echo "==> building onedir flavour for $PLAT_TAG"
run_pyi onedir
ONEDIR_BASE="plantuml-onedir-${PLAT_TAG}"
rm -rf "$OUT/$ONEDIR_BASE"
mv "$ROOT/dist/plantuml" "$OUT/$ONEDIR_BASE"

# Same hardened-runtime stripping for every binary inside the onedir tree.
if [[ "$(uname -s)" = "Darwin" ]]; then
    find "$OUT/$ONEDIR_BASE" -type f \( -name '*.dylib' -o -name '*.jnilib' \
            -o -name 'java' -o -name 'plantuml' -o -perm -u+x \) \
        -exec sh -c 'codesign --remove-signature "$1" 2>/dev/null; \
                     codesign --force --sign - --timestamp=none "$1" 2>/dev/null' \
              sh {} \; 2>/dev/null || true
fi

ZIP_NAME="$OUT/${ONEDIR_BASE}.zip"
rm -f "$ZIP_NAME"
# cd into $OUT so we always pass *relative* paths to the archiver. Windows
# Git Bash converts $OUT to /d/a/... which Python (or zip) on Windows
# misinterprets as a drive-root path; relative paths sidestep the issue.
if command -v zip >/dev/null 2>&1; then
    (cd "$OUT" && zip -qr "${ONEDIR_BASE}.zip" "$ONEDIR_BASE")
else
    (cd "$OUT" && python -c \
        "import shutil; shutil.make_archive('${ONEDIR_BASE}', 'zip', '.', '${ONEDIR_BASE}')")
fi
ls -lh "$ZIP_NAME"
rm -rf "$OUT/$ONEDIR_BASE"

echo "==> done"
ls -lh "$OUT/"
