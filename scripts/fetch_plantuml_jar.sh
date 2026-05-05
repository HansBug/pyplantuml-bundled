#!/usr/bin/env bash
# Download the PlantUML jar with sha256 verification.  Idempotent.
set -euo pipefail

PLANTUML_VERSION="${PLANTUML_VERSION:-1.2024.7}"
PLANTUML_SHA256="${PLANTUML_SHA256:-e34c12bbe9944f1f338ca3d88c9b116b86300cc8e90b35c4086b825b5ae96d24}"
URL="https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml-${PLANTUML_VERSION}.jar"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/src/pyplantuml/plantuml.jar"

if [[ -f "$DEST" ]]; then
    actual=$(sha256sum "$DEST" | awk '{print $1}')
    if [[ "$actual" == "$PLANTUML_SHA256" ]]; then
        echo "plantuml.jar already present and matches sha256 ($PLANTUML_VERSION)"
        exit 0
    fi
    echo "plantuml.jar exists but sha256 does not match — re-downloading"
fi

mkdir -p "$(dirname "$DEST")"
echo "Fetching PlantUML $PLANTUML_VERSION ..."
curl -fsSL --retry 5 --retry-delay 2 -o "$DEST.tmp" "$URL"

actual=$(sha256sum "$DEST.tmp" | awk '{print $1}')
if [[ "$actual" != "$PLANTUML_SHA256" ]]; then
    echo "FATAL: sha256 mismatch for plantuml-${PLANTUML_VERSION}.jar" >&2
    echo "  expected: $PLANTUML_SHA256" >&2
    echo "  actual:   $actual" >&2
    rm -f "$DEST.tmp"
    exit 1
fi
mv "$DEST.tmp" "$DEST"
echo "ok: $DEST ($(wc -c <"$DEST") bytes)"
