#!/usr/bin/env sh
# Stage-2 helper: external-perspective smoketest of a portable plantuml
# binary.  No python, no java, no jdk — only the binary itself runs.
#
# Reads:
#   $PLANTUML      – path to the portable executable
#
# Five checks, each independent: -version banner, -tpng on a simple
# diagram, -tsvg on a simple diagram, -checkonly on a valid diagram,
# -tpng on a CJK diagram with a substantial-byte-size sanity bound.
#
# POSIX-portable so it runs identically on alpine ash, debian /
# ubuntu / rockylinux / fedora bash, macOS bash, and Windows
# git-bash (msys2).
set -e

[ -n "${PLANTUML:-}" ] || { echo "FATAL: \$PLANTUML not set" >&2; exit 2; }
[ -x "$PLANTUML" ] || { echo "FATAL: $PLANTUML not executable" >&2; exit 2; }

WORK=$(mktemp -d 2>/dev/null || mktemp -d -t plantuml)
cd "$WORK"

echo "smoketest dir : $WORK"
echo "plantuml exe  : $PLANTUML"

# ---- 1. version banner ------------------------------------------------
"$PLANTUML" -version > version.txt
grep -q "PlantUML version" version.txt || {
    echo "smoketest 1/5 FAIL: -version did not print 'PlantUML version'" >&2
    cat version.txt >&2
    exit 1
}
echo "smoketest 1/5 PASS  -version banner OK"

# ---- 2. simple ASCII puml -> PNG --------------------------------------
cat > hello.puml <<'PUML'
@startuml
Alice -> Bob : hello
Bob --> Alice : hi
@enduml
PUML
"$PLANTUML" -tpng hello.puml
test -f hello.png || {
    echo "smoketest 2/5 FAIL: hello.png not produced" >&2
    exit 1
}
# PNG magic 89 50 4E 47 0D 0A 1A 0A
HEAD_HEX=$(head -c 8 hello.png | od -An -tx1 | tr -d ' \n')
case "$HEAD_HEX" in
    89504e470d0a1a0a) ;;
    *)
        echo "smoketest 2/5 FAIL: hello.png is not a PNG (header=$HEAD_HEX)" >&2
        exit 1
        ;;
esac
HELLO_PNG_SIZE=$(wc -c < hello.png | tr -d ' ')
echo "smoketest 2/5 PASS  -tpng produced valid PNG ($HELLO_PNG_SIZE bytes)"

# ---- 3. simple puml -> SVG --------------------------------------------
"$PLANTUML" -tsvg hello.puml
test -f hello.svg || {
    echo "smoketest 3/5 FAIL: hello.svg not produced" >&2
    exit 1
}
grep -q "<svg " hello.svg || {
    echo "smoketest 3/5 FAIL: hello.svg has no <svg root element" >&2
    head -3 hello.svg >&2
    exit 1
}
echo "smoketest 3/5 PASS  -tsvg produced valid SVG"

# ---- 4. -checkonly on valid puml exits 0 ------------------------------
"$PLANTUML" -checkonly hello.puml
echo "smoketest 4/5 PASS  -checkonly exited 0 on valid puml"

# ---- 5. CJK render — substantial PNG byte size proves real glyphs -----
cat > cjk.puml <<'PUML'
@startuml
title 中文标题：测试
A -> B : 你好世界
B --> A : こんにちは
@enduml
PUML
"$PLANTUML" -tpng cjk.puml
test -f cjk.png || {
    echo "smoketest 5/5 FAIL: cjk.png not produced" >&2
    exit 1
}
# Tofu rendering of the same diagram lands at <5 KB; real CJK glyphs
# yield >=8 KB even for this tiny fixture.  Assert >=4 KB as a
# conservative lower bound that still rejects tofu collapse.
CJK_SIZE=$(wc -c < cjk.png | tr -d ' ')
if [ "$CJK_SIZE" -lt 4000 ]; then
    echo "smoketest 5/5 FAIL: cjk.png suspiciously small ($CJK_SIZE bytes — likely tofu)" >&2
    exit 1
fi
echo "smoketest 5/5 PASS  CJK PNG = $CJK_SIZE bytes"

echo "----"
echo "all 5 portable smoketest checks PASSED"
