#!/usr/bin/env bash
# Re-render docs/img/cli-demo.gif from the committed scenario sources.
#
# Source-of-truth assets (committed to the repo):
#   docs/cli-demo.scenario.json   – VHS scenario (steps + theme)
#   docs/cli-demo.setup.sh        – bash sourced before any visible step
#                                    (PS1, fake pip output, .puml syntax-highlight)
#   docs/cli-demo.hello.puml      – the example diagram
#
# This script stages those into /tmp/cli-demo (the cwd the scenario
# references) and invokes the terminal-capture-workflow renderer.
# Override the renderer location via SKILL_ROOT if it lives elsewhere.
#
# Requires: VHS, ttyd, and Python (for the renderer wrapper).  Run
# `python "$SKILL_ROOT/scripts/terminal_capture.py" check` first if
# anything is missing.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Ensure plantuml is on PATH (the demo invokes the real binary for
# render / checkonly / version).  The project's own venv at venv/
# carries the editable install.
if ! command -v plantuml >/dev/null 2>&1; then
    if [ -f "$REPO_ROOT/venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source "$REPO_ROOT/venv/bin/activate"
    fi
fi
if ! command -v plantuml >/dev/null 2>&1; then
    echo "FATAL: 'plantuml' not on PATH.  Activate the project venv first." >&2
    exit 1
fi

# Stage scenario inputs.
mkdir -p /tmp/cli-demo
cp -f docs/cli-demo.setup.sh    /tmp/cli-demo/setup.sh
cp -f docs/cli-demo.hello.puml  /tmp/cli-demo/hello.puml
rm -f /tmp/cli-demo/hello.png   # let the demo regenerate it

SKILL_ROOT="${SKILL_ROOT:-$HOME/.claude/skills/terminal-capture-workflow}"
if [ ! -f "$SKILL_ROOT/scripts/terminal_capture.py" ]; then
    echo "FATAL: terminal-capture-workflow renderer not found at $SKILL_ROOT" >&2
    echo "Set SKILL_ROOT or install the skill." >&2
    exit 1
fi

OUT_ROOT=/tmp/cli-demo-render
rm -rf "$OUT_ROOT"
python "$SKILL_ROOT/scripts/terminal_capture.py" render vhs \
    "$REPO_ROOT/docs/cli-demo.scenario.json" \
    --output-root "$OUT_ROOT"

NEW_GIF="$OUT_ROOT/vhs/pyplantuml-cli-demo/pyplantuml-cli-demo.gif"
test -s "$NEW_GIF" || { echo "FATAL: rendered GIF missing or empty: $NEW_GIF" >&2; exit 2; }

DEST="$REPO_ROOT/docs/img/cli-demo.gif"
cp -f "$NEW_GIF" "$DEST"
echo "Updated: $DEST  ($(wc -c <"$DEST") bytes)"
