#!/usr/bin/env bash
# Download the PlantUML jar with sha256 verification.  Idempotent.
set -euo pipefail

PLANTUML_VERSION="${PLANTUML_VERSION:-1.2024.7}"
PLANTUML_SHA256="${PLANTUML_SHA256:-e34c12bbe9944f1f338ca3d88c9b116b86300cc8e90b35c4086b825b5ae96d24}"
URL="https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml-${PLANTUML_VERSION}.jar"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/src/pyplantuml/plantuml.jar"

# Portable sha256: macOS has shasum, Linux has sha256sum, Windows Git Bash
# has neither.  Python ships with hashlib on every CI runner.
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}

if [[ -f "$DEST" ]]; then
    actual=$(sha256_of "$DEST")
    if [[ "$actual" == "$PLANTUML_SHA256" ]]; then
        echo "plantuml.jar already present and matches sha256 ($PLANTUML_VERSION)"
        exit 0
    fi
    echo "plantuml.jar exists but sha256 does not match — re-downloading"
fi

mkdir -p "$(dirname "$DEST")"
echo "Fetching PlantUML $PLANTUML_VERSION ..."
curl -fsSL --retry 5 --retry-delay 2 -o "$DEST.tmp" "$URL"

actual=$(sha256_of "$DEST.tmp")
if [[ "$actual" != "$PLANTUML_SHA256" ]]; then
    echo "FATAL: sha256 mismatch for plantuml-${PLANTUML_VERSION}.jar" >&2
    echo "  expected: $PLANTUML_SHA256" >&2
    echo "  actual:   $actual" >&2
    rm -f "$DEST.tmp"
    exit 1
fi
mv "$DEST.tmp" "$DEST"
echo "ok: $DEST ($(wc -c <"$DEST") bytes)"
