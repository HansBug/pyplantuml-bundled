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
ls -lh "$OUT/$ONEFILE_NAME"

# ---- onedir + zip ------------------------------------------------------
echo "==> building onedir flavour for $PLAT_TAG"
run_pyi onedir
ONEDIR_BASE="plantuml-onedir-${PLAT_TAG}"
rm -rf "$OUT/$ONEDIR_BASE"
mv "$ROOT/dist/plantuml" "$OUT/$ONEDIR_BASE"

ZIP_NAME="$OUT/${ONEDIR_BASE}.zip"
rm -f "$ZIP_NAME"
case "$(uname -s)" in
    Linux|Darwin) (cd "$OUT" && zip -qr "${ONEDIR_BASE}.zip" "$ONEDIR_BASE") ;;
    *) python -c "import shutil; shutil.make_archive(r'$OUT/${ONEDIR_BASE}', 'zip', r'$OUT', r'$ONEDIR_BASE')" ;;
esac
ls -lh "$ZIP_NAME"
rm -rf "$OUT/$ONEDIR_BASE"

echo "==> done"
ls -lh "$OUT/"
