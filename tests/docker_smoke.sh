#!/bin/sh
# In-container smoke test. Runs INSIDE a python:X-slim container with the
# wheel mounted at /wheel. Fails loud and early.
set -eu

# ---- 1. Prove the image has zero Java -----------------------------------
echo "=== [1/5] prove no java in image ==="
if command -v java >/dev/null 2>&1; then
    echo "FAIL: java unexpectedly present at $(command -v java)" >&2
    exit 11
fi
[ -d /usr/lib/jvm ] && { echo "FAIL: /usr/lib/jvm exists"; exit 12; }
echo "ok: no java binary, no /usr/lib/jvm"

# ---- 2. Install the wheel ----------------------------------------------
echo "=== [2/5] pip install the wheel ==="
python -V
pip install --quiet --disable-pip-version-check /wheel/*.whl
echo "ok: wheel installed"

# ---- 3. Smoke: CLI render PNG ------------------------------------------
echo "=== [3/5] CLI render png + svg ==="
mkdir -p /out
cat >/out/in.puml <<'EOF'
@startuml
title 中文标题 demo
Alice -> Bob: 你好
Bob --> Alice: hi
@enduml
EOF

plantuml -tpng -o /out /out/in.puml
test -s /out/in.png || { echo "FAIL: png missing/empty"; exit 21; }
PNG_BYTES=$(wc -c < /out/in.png)
[ "$PNG_BYTES" -gt 1000 ] || { echo "FAIL: png too small ($PNG_BYTES bytes)"; exit 22; }
python -c "
import sys
with open('/out/in.png','rb') as f: head = f.read(8)
sys.exit(0 if head == b'\x89PNG\r\n\x1a\n' else 1)
" || { echo "FAIL: not a PNG (magic bytes wrong)"; exit 23; }
echo "ok: PNG $PNG_BYTES bytes"

plantuml -tsvg -o /out /out/in.puml
test -s /out/in.svg || { echo "FAIL: svg missing"; exit 24; }
grep -q '<svg ' /out/in.svg || { echo "FAIL: svg malformed"; exit 25; }
# Chinese -> SVG numeric entity (e.g., 中=&#20013;)
grep -q '&#20013;' /out/in.svg || { echo "FAIL: SVG missing CJK entity"; exit 26; }
echo "ok: SVG with CJK entities"

# ---- 4. Static check ----------------------------------------------------
echo "=== [4/5] -checkonly ==="
plantuml -checkonly /out/in.puml
echo "ok: checkonly exit 0"

cat >/out/bad.puml <<'EOF'
@startuml
Alice -> @@@@ broken syntax
@enduml
EOF
if plantuml -checkonly /out/bad.puml >/dev/null 2>&1; then
    echo "FAIL: bad puml unexpectedly passed checkonly" >&2
    exit 41
fi
echo "ok: bad puml correctly rejected"

# ---- 4b. CJK rendering: render text-only PNG so visual check is easy ----
echo "=== [4b] CJK render to /verify/cjk.png ==="
mkdir -p /verify
cat >/out/cjk.puml <<'EOF'
@startuml
skinparam dpi 144
skinparam defaultFontSize 18
skinparam backgroundColor #FFFFFF
title 中文标题：跨平台部署架构
participant "前端 用户" as U
participant "API 服务" as S
participant "数据库 MySQL" as D
U -> S : 请求登录\n(账号 / 密码)
S -> D : 查询用户记录
D --> S : 返回认证信息
S --> U : 登录成功\n返回 token
note right of S
  日本語: こんにちは
  한국어: 안녕하세요
  English: Hello
end note
@enduml
EOF
plantuml -tpng -o /verify /out/cjk.puml
test -s /verify/cjk.png || { echo "FAIL: cjk.png missing"; exit 51; }
CJK_BYTES=$(wc -c < /verify/cjk.png)
echo "ok: cjk.png produced ($CJK_BYTES bytes)"
# A PNG containing actual rendered text (not all-tofu) tends to be >=8KB.
# Tofu-only PNGs compress much smaller because all glyphs are identical squares.
[ "$CJK_BYTES" -gt 8000 ] || { echo "WARN: CJK PNG suspiciously small ($CJK_BYTES) — possible tofu"; exit 52; }

# ---- 5. Python API ------------------------------------------------------
echo "=== [5/5] python API ==="
python - <<'PY'
import pyplantuml as pu, pathlib, tempfile, sys
ver = pu.version()
assert "PlantUML version" in ver, ver
assert "OpenJDK" in ver, ver
assert pu.check("/out/in.puml") is True
with tempfile.TemporaryDirectory() as d:
    pu.render("/out/in.puml", output_dir=d, fmt="svg")
    files = list(pathlib.Path(d).glob("*.svg"))
    assert files and files[0].stat().st_size > 500, files
print("ok: python API")
print("---")
print(ver)
PY

echo
echo "ALL SMOKE TESTS PASSED on $(python -V 2>&1)"
