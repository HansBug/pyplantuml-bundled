#!/usr/bin/env bash
# Switch the entire repo to a target PlantUML version (or just bump
# the wrapper revision while keeping the upstream version pinned).
#
# Versioning convention: <plantuml-version>.<wrapper-revision>
#   1.2024.8.0  ← first release for upstream PlantUML 1.2024.8
#   1.2024.8.1  ← wrapper-only fix (CI, staging, click compat, …)
#   1.2024.8.2  ← another wrapper-only fix
#   1.2024.9.0  ← new upstream PlantUML version
#
# Usage:
#   scripts/bump_plantuml_version.sh <plantuml-version> [wrapper-rev]
#   scripts/bump_plantuml_version.sh 1.2024.8                # → 1.2024.8.0
#   scripts/bump_plantuml_version.sh 1.2024.8 2              # → 1.2024.8.2
#   scripts/bump_plantuml_version.sh --wrapper-only          # bump only trailing seg
#   scripts/bump_plantuml_version.sh --print-current         # show current version + plantuml
#
# Side effects (all in the working tree, no git operations):
#   - downloads plantuml-<version>.jar to a temp file ONLY to compute
#     sha256 (then deletes it; the gitignored jar in src/pyplantuml/
#     is left alone — it's a build-time concern handled by
#     fetch_plantuml_jar.sh)
#   - rewrites:
#       pyproject.toml                   (project.version)
#       src/pyplantuml/__init__.py       (__version__)
#       scripts/fetch_plantuml_jar.sh    (PLANTUML_VERSION + PLANTUML_SHA256 defaults)
#       CHANGELOG.md                     (prepends a new heading; body left blank)
#       README.md                        (PlantUML badge + bundled-version mention)
#
# Exits non-zero with a clear message on any failure.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

# ----- portable sha256 (mac / linux / git-bash without sha256sum) -----
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
    fi
}

# ----- read CURRENT (plantuml_version, wrapper_rev) from pyproject.toml -----
read_current() {
    local v
    v=$(grep -E '^version\s*=\s*"' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
    if [[ -z "$v" ]]; then
        echo "could not read current version from pyproject.toml" >&2
        exit 2
    fi
    # split into 4 segments: cur_plantuml = first 3, cur_wrapper = 4th (default 0)
    IFS='.' read -ra parts <<< "$v"
    if [[ ${#parts[@]} -lt 3 || ${#parts[@]} -gt 4 ]]; then
        echo "current version '$v' is not 3- or 4-segment; cannot parse" >&2
        exit 2
    fi
    cur_plantuml="${parts[0]}.${parts[1]}.${parts[2]}"
    cur_wrapper="${parts[3]:-0}"
    cur_full="$v"
}

# ----- argument parsing -----
WRAPPER_ONLY=0
PRINT_ONLY=0
TARGET_PLANTUML=""
TARGET_WRAPPER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            ;;
        --print-current)
            PRINT_ONLY=1
            shift
            ;;
        --wrapper-only)
            WRAPPER_ONLY=1
            shift
            ;;
        --) shift; break ;;
        -*) echo "unknown option: $1" >&2; usage ;;
        *)
            if [[ -z "$TARGET_PLANTUML" ]]; then
                TARGET_PLANTUML="$1"
            elif [[ -z "$TARGET_WRAPPER" ]]; then
                TARGET_WRAPPER="$1"
            else
                echo "too many positional args" >&2; usage
            fi
            shift
            ;;
    esac
done

read_current

if [[ "$PRINT_ONLY" -eq 1 ]]; then
    echo "current version : $cur_full"
    echo "  plantuml      : $cur_plantuml"
    echo "  wrapper rev   : $cur_wrapper"
    exit 0
fi

if [[ "$WRAPPER_ONLY" -eq 1 ]]; then
    if [[ -n "$TARGET_PLANTUML" ]]; then
        echo "--wrapper-only and explicit version are mutually exclusive" >&2
        exit 2
    fi
    NEW_PLANTUML="$cur_plantuml"
    NEW_WRAPPER=$((cur_wrapper + 1))
else
    if [[ -z "$TARGET_PLANTUML" ]]; then
        echo "missing target PlantUML version" >&2
        usage
    fi
    if ! [[ "$TARGET_PLANTUML" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "target plantuml version must be 3-segment N.N.N (got: $TARGET_PLANTUML)" >&2
        exit 2
    fi
    NEW_PLANTUML="$TARGET_PLANTUML"
    if [[ -n "$TARGET_WRAPPER" ]]; then
        if ! [[ "$TARGET_WRAPPER" =~ ^[0-9]+$ ]]; then
            echo "wrapper rev must be a non-negative integer (got: $TARGET_WRAPPER)" >&2
            exit 2
        fi
        NEW_WRAPPER="$TARGET_WRAPPER"
    elif [[ "$NEW_PLANTUML" == "$cur_plantuml" ]]; then
        # Same upstream as current: bump wrapper, do not silently regress to .0
        NEW_WRAPPER=$((cur_wrapper + 1))
    else
        # New upstream: start at .0
        NEW_WRAPPER=0
    fi
fi

NEW_VERSION="${NEW_PLANTUML}.${NEW_WRAPPER}"

if [[ "$NEW_VERSION" == "$cur_full" ]]; then
    echo "new version equals current ($cur_full) — nothing to do" >&2
    exit 0
fi

echo "bumping: $cur_full → $NEW_VERSION"
echo "  plantuml: $cur_plantuml → $NEW_PLANTUML"
echo "  wrapper:  $cur_wrapper → $NEW_WRAPPER"

# ----- compute new sha256 of plantuml.jar (only when upstream changes) -----
NEW_SHA256=""
if [[ "$NEW_PLANTUML" != "$cur_plantuml" ]]; then
    URL="https://github.com/plantuml/plantuml/releases/download/v${NEW_PLANTUML}/plantuml-${NEW_PLANTUML}.jar"
    TMP=$(mktemp -t pmjar.XXXXXX)
    trap 'rm -f "$TMP"' EXIT
    echo "fetching $URL to compute sha256 ..."
    curl -fsSL --retry 5 --retry-delay 2 -o "$TMP" "$URL"
    NEW_SHA256=$(sha256_of "$TMP")
    SIZE=$(wc -c <"$TMP" | tr -d ' ')
    echo "  size  : $SIZE bytes"
    echo "  sha256: $NEW_SHA256"
    rm -f "$TMP"
    trap - EXIT
fi

# ----- rewrite pyproject.toml -----
python3 - "$cur_full" "$NEW_VERSION" <<'PY'
import re, sys
old, new = sys.argv[1], sys.argv[2]
path = "pyproject.toml"
src = open(path).read()
pattern = re.compile(r'^(version\s*=\s*)"' + re.escape(old) + r'"', re.MULTILINE)
out, n = pattern.subn(r'\1"' + new + '"', src)
if n != 1:
    print("ERROR: failed to rewrite pyproject.toml version (matches=%d)" % n, file=sys.stderr)
    sys.exit(3)
open(path, "w").write(out)
print("ok: pyproject.toml")
PY

# ----- rewrite src/pyplantuml/__init__.py -----
python3 - "$cur_full" "$NEW_VERSION" <<'PY'
import re, sys
old, new = sys.argv[1], sys.argv[2]
path = "src/pyplantuml/__init__.py"
src = open(path).read()
pattern = re.compile(r'^(__version__\s*=\s*)"' + re.escape(old) + r'"', re.MULTILINE)
out, n = pattern.subn(r'\1"' + new + '"', src)
if n != 1:
    print("ERROR: failed to rewrite __init__.py __version__ (matches=%d)" % n, file=sys.stderr)
    sys.exit(3)
open(path, "w").write(out)
print("ok: src/pyplantuml/__init__.py")
PY

# ----- rewrite scripts/fetch_plantuml_jar.sh -----
if [[ "$NEW_PLANTUML" != "$cur_plantuml" ]]; then
    python3 - "$cur_plantuml" "$NEW_PLANTUML" "$NEW_SHA256" <<'PY'
import re, sys
old_v, new_v, new_sha = sys.argv[1], sys.argv[2], sys.argv[3]
path = "scripts/fetch_plantuml_jar.sh"
src = open(path).read()
out = src
pat_v = re.compile(r'^(PLANTUML_VERSION\s*=\s*"\$\{PLANTUML_VERSION:-)' + re.escape(old_v) + r'(\}")', re.MULTILINE)
out, n_v = pat_v.subn(r'\g<1>' + new_v + r'\g<2>', out)
if n_v != 1:
    print("ERROR: PLANTUML_VERSION default not rewritten (matches=%d)" % n_v, file=sys.stderr)
    sys.exit(3)
pat_s = re.compile(r'^(PLANTUML_SHA256\s*=\s*"\$\{PLANTUML_SHA256:-)[0-9a-f]{64}(\}")', re.MULTILINE)
out, n_s = pat_s.subn(r'\g<1>' + new_sha + r'\g<2>', out)
if n_s != 1:
    print("ERROR: PLANTUML_SHA256 default not rewritten (matches=%d)" % n_s, file=sys.stderr)
    sys.exit(3)
open(path, "w").write(out)
print("ok: scripts/fetch_plantuml_jar.sh")
PY
fi

# ----- prepend a new CHANGELOG heading -----
DATE=$(date -u +%Y-%m-%d)
python3 - "$NEW_VERSION" "$DATE" "$NEW_PLANTUML" "$cur_plantuml" <<'PY'
import sys
new_v, date, new_p, old_p = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
path = "CHANGELOG.md"
src = open(path).read()
# Find the first existing version heading, prepend the new one above it.
import re
m = re.search(r'^## \[', src, re.MULTILINE)
if not m:
    print("ERROR: no existing '## [...]' heading in CHANGELOG.md", file=sys.stderr)
    sys.exit(3)
upstream_changed = (new_p != old_p)
note = ("Bundled `plantuml.jar` updated to %s." % new_p) if upstream_changed else "Wrapper-only revision (no upstream PlantUML change)."
new_section = "## [%s] — %s\n\n%s\n\n_(fill in details)_\n\n" % (new_v, date, note)
out = src[:m.start()] + new_section + src[m.start():]
open(path, "w").write(out)
print("ok: CHANGELOG.md (added [%s] heading)" % new_v)
PY

# ----- README badge + version mention -----
python3 - "$cur_plantuml" "$NEW_PLANTUML" "$cur_full" "$NEW_VERSION" <<'PY'
import re, sys
old_p, new_p, old_v, new_v = sys.argv[1:5]
path = "README.md"
src = open(path).read()
out = src
n_total = 0
# Badge: img.shields.io/badge/plantuml-<version>-orange  + linkable label "PlantUML: <version>"
out, n = re.subn(re.escape(old_p), new_p, out)
n_total += n
# Also catch the old full version string just in case it is mentioned literally.
out, n2 = re.subn(re.escape(old_v), new_v, out)
n_total += n2
if n_total == 0:
    print("warning: no replacements made in README.md", file=sys.stderr)
else:
    open(path, "w").write(out)
    print("ok: README.md (%d substitutions)" % n_total)
PY

echo
echo "Done.  Review the diff before committing."
echo "  git diff --stat"
echo "  git diff CHANGELOG.md   # fill in the empty body for [$NEW_VERSION]"
