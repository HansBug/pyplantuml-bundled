#!/usr/bin/env bash
# Stage the Linux native font subsystem (libfontconfig + freetype + chain)
# plus the vendored CJK fonts into src/pyplantuml/runtime/linux-<arch>/.
#
# Must be run INSIDE the same container that builds the wheel, so the
# .so chain matches the wheel's libc / glibc baseline.
#
# Detects manylinux (yum/dnf) vs musllinux (apk) automatically.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ARCH=$(uname -m)
case "$ARCH" in
    x86_64|amd64) ARCH=x86_64 ;;
    aarch64|arm64) ARCH=aarch64 ;;
    *) echo "FATAL: unsupported arch $ARCH" >&2; exit 1 ;;
esac

DEST="$ROOT/src/pyplantuml/runtime/linux-$ARCH"
mkdir -p "$DEST/lib" "$DEST/fonts"

# ---- 1. detect package manager and install fontconfig + deps ----------
# We list every .so we want, plus the rpm/apk packages that ship them.
# All non-trivial transitive deps are spelled out so we don't depend on
# the package manager's "Recommends" set.
# Install required packages first (everything libfreetype + JRE rendering
# absolutely needs); install optional libs (brotli for WOFF2, harfbuzz
# for advanced font shaping, graphite2 for harfbuzz) one at a time so a
# missing package on some old distro/arch combos does not abort the
# whole stage. The lib-copy loop later already handles "MISS" gracefully
# when a .so is not present on disk.
_install_optional() {
    local mgr="$1"; shift
    for pkg in "$@"; do
        case "$mgr" in
            apk) apk add --no-cache "$pkg" 1>&2 || \
                 echo "WARN: optional pkg $pkg unavailable, skipping" >&2 ;;
            dnf) dnf install -y "$pkg" 1>&2 || \
                 echo "WARN: optional pkg $pkg unavailable, skipping" >&2 ;;
            yum) yum install -y "$pkg" 1>&2 || \
                 echo "WARN: optional pkg $pkg unavailable, skipping" >&2 ;;
            apt) apt-get install -y --no-install-recommends "$pkg" 1>&2 || \
                 echo "WARN: optional pkg $pkg unavailable, skipping" >&2 ;;
        esac
    done
}

if command -v apk >/dev/null 2>&1; then
    PKG=apk
    apk add --no-cache fontconfig freetype libpng expat libuuid zlib 1>&2
    _install_optional apk brotli-libs harfbuzz
elif command -v dnf >/dev/null 2>&1; then
    PKG=dnf
    dnf install -y fontconfig freetype libpng expat libuuid zlib 1>&2
    _install_optional dnf brotli harfbuzz
elif command -v yum >/dev/null 2>&1; then
    PKG=yum
    yum install -y fontconfig freetype libpng expat libuuid zlib 1>&2
    _install_optional yum brotli harfbuzz
elif command -v apt-get >/dev/null 2>&1; then
    PKG=apt
    apt-get update -qq 1>&2
    apt-get install -y --no-install-recommends fontconfig libfreetype6 libpng16-16 \
        libexpat1 libuuid1 zlib1g 1>&2
    _install_optional apt libbrotli1 libharfbuzz0b
else
    echo "FATAL: no supported package manager (apk/dnf/yum/apt) found" >&2
    exit 1
fi
echo "package manager: $PKG"

# ---- 2. copy the .so chain --------------------------------------------
# We search common library directories explicitly instead of `ldconfig -p`
# because awk's early-exit pattern creates SIGPIPE that breaks pipefail.
SEARCH_DIRS=(
    /usr/lib64
    /usr/lib
    /lib64
    /lib
    /usr/lib/x86_64-linux-gnu
    /usr/lib/aarch64-linux-gnu
    /usr/lib/x86_64-linux-musl
    /usr/lib/aarch64-linux-musl
)

needed=(
    libfontconfig.so.1
    libfreetype.so.6
    libpng16.so.16
    libexpat.so.1
    libuuid.so.1
    libz.so.1
    libbrotlidec.so.1
    libbrotlicommon.so.1
    # libharfbuzz is a runtime dep of OpenJDK 17's libfontmanager.so;
    # bundle it so headless rendering works on slim/scratch targets.
    libharfbuzz.so.0
    libgraphite2.so.3
)

found_count=0
for so in "${needed[@]}"; do
    src=""
    for d in "${SEARCH_DIRS[@]}"; do
        if [[ -e "$d/$so" ]]; then
            src="$d/$so"
            break
        fi
    done
    if [[ -z "$src" ]]; then
        echo "WARN: could not locate $so — skipping" >&2
        continue
    fi
    cp -L "$src" "$DEST/lib/"
    echo "  copied $so  <-  $src"
    found_count=$((found_count + 1))
done

# Sanity: at minimum we must have libfontconfig + libfreetype.
if [[ ! -e "$DEST/lib/libfontconfig.so.1" ]] || [[ ! -e "$DEST/lib/libfreetype.so.6" ]]; then
    echo "FATAL: libfontconfig.so.1 and/or libfreetype.so.6 not staged" >&2
    exit 1
fi
echo "staged $found_count of ${#needed[@]} libraries"

# ---- 3. vendored fonts -------------------------------------------------
VENDOR_DIR="$ROOT/vendored/fonts"
if [[ ! -d "$VENDOR_DIR" ]]; then
    echo "FATAL: vendored fonts not found at $VENDOR_DIR" >&2
    exit 1
fi
cp "$VENDOR_DIR"/DejaVuSans.ttf       "$DEST/fonts/"
cp "$VENDOR_DIR"/DejaVuSans-Bold.ttf  "$DEST/fonts/"
cp "$VENDOR_DIR"/wqy-microhei.ttc     "$DEST/fonts/"

echo "----"
ls -lh "$DEST/lib"
echo "----"
ls -lh "$DEST/fonts"
echo "ok: staged at $DEST  ($(du -sh "$DEST" | awk '{print $1}'))"
