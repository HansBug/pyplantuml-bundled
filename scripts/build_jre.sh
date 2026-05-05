#!/usr/bin/env bash
# Build a minimal JRE with jlink for the current platform.
# Requires JAVA_HOME pointing at a JDK >= 11 (we use 17 in CI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/src/pyplantuml/jre"

if [[ -z "${JAVA_HOME:-}" ]]; then
    echo "FATAL: JAVA_HOME is not set" >&2
    exit 1
fi
if [[ ! -x "$JAVA_HOME/bin/jlink" && ! -x "$JAVA_HOME/bin/jlink.exe" ]]; then
    echo "FATAL: jlink not found under JAVA_HOME=$JAVA_HOME" >&2
    exit 1
fi

# Module set chosen empirically:
#   java.base, java.desktop, java.xml, java.scripting, java.naming,
#   java.logging, java.management, java.sql, jdk.zipfs, jdk.crypto.ec,
#   jdk.unsupported
# Anything less than this and PlantUML either fails to start or refuses
# to render PNG/SVG (java.desktop/java.scripting are non-negotiable).
MODULES="java.base,java.desktop,java.xml,java.scripting,java.naming,java.logging,java.management,java.sql,jdk.zipfs,jdk.crypto.ec,jdk.unsupported"

rm -rf "$DEST"

JLINK="$JAVA_HOME/bin/jlink"
[[ -x "$JLINK" ]] || JLINK="$JAVA_HOME/bin/jlink.exe"

"$JLINK" \
    --add-modules "$MODULES" \
    --strip-debug \
    --no-man-pages \
    --no-header-files \
    --compress=2 \
    --output "$DEST"

# Sanity check: the bundled java must run.
JAVA_BIN="$DEST/bin/java"
[[ -x "$JAVA_BIN" ]] || JAVA_BIN="$DEST/bin/java.exe"
"$JAVA_BIN" -version
echo "ok: jre at $DEST ($(du -sh "$DEST" | awk '{print $1}'))"
