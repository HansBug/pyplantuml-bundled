#!/bin/bash

# Counts lines of Python source / comments in the repo via `cloc`.
# Used by the badge workflow to populate the loc / comments shields
# (see .github/workflows/badge.yml).  Pass --loc / --comments /
# --percentage to print one number suitable for an env var.

# Get the location of this script.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Run cloc — Python only, markdown summary, last line is the SUM:.
# Exclude generated / vendored / build artifacts so the count
# reflects only first-party code: venv (developer-installed deps),
# jre (jlink build output), pyinstaller-build/dist (PyInstaller
# stages), build / dist / *.egg-info (setuptools), node_modules
# (if any), and CI's wheelhouse output.
SUMMARY="$(cloc "${SCRIPT_DIR}" \
  --include-lang="Python" \
  --exclude-dir=venv,.venv,jre,pyinstaller-build,pyinstaller-dist,build,dist,wheelhouse,node_modules \
  --not-match-d='\.egg-info$' \
  --md | tail -1)"

# Split SUMMARY (e.g. "SUM:|12|345|678|1234") into components.
IFS='|' read -r -a TOKENS <<<"$SUMMARY"

NUMBER_OF_FILES=${TOKENS[1]}
COMMENT_LINES=${TOKENS[3]}
LINES_OF_CODE=${TOKENS[4]}

if [[ $# -eq 0 ]]; then
  awk -v a=$LINES_OF_CODE \
    'BEGIN {printf "Lines of source code: %6.1fk\n", a/1000}'
  awk -v a=$COMMENT_LINES \
    'BEGIN {printf "Lines of comments:    %6.1fk\n", a/1000}'
  awk -v a=$COMMENT_LINES -v b=$LINES_OF_CODE \
    'BEGIN {printf "Comment Percentage:   %6.1f%\n", 100*a/b}'
  exit 0
fi

if [[ $* == *--loc* ]]; then
  awk -v a=$LINES_OF_CODE \
    'BEGIN {printf "%.1fk\n", a/1000}'
fi

if [[ $* == *--comments* ]]; then
  awk -v a=$COMMENT_LINES \
    'BEGIN {printf "%.1fk\n", a/1000}'
fi

if [[ $* == *--percentage* ]]; then
  awk -v a=$COMMENT_LINES -v b=$LINES_OF_CODE \
    'BEGIN {printf "%.1f\n", 100*a/b}'
fi
