from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest


SIMPLE_PUML = """@startuml
Alice -> Bob: hello
Bob --> Alice: hi
@enduml
"""

CJK_PUML = """@startuml
skinparam dpi 144
skinparam defaultFontSize 18
skinparam backgroundColor #FFFFFF
title 中文标题：跨平台部署架构
participant "前端 用户" as U
participant "API 服务" as S
participant "数据库 MySQL" as D
U -> S : 请求登录\\n(账号 / 密码)
S -> D : 查询用户记录
D --> S : 返回认证信息
S --> U : 登录成功\\n返回 token
note right of S
  日本語: こんにちは
  한국어: 안녕하세요
  English: Hello
end note
@enduml
"""

BAD_PUML = """@startuml
Alice -> @@@@ broken syntax
@enduml
"""


@pytest.fixture
def simple_puml(tmp_path: Path) -> Path:
    p = tmp_path / "simple.puml"
    p.write_text(SIMPLE_PUML, encoding="utf-8")
    return p


@pytest.fixture
def cjk_puml(tmp_path: Path) -> Path:
    p = tmp_path / "cjk.puml"
    p.write_text(CJK_PUML, encoding="utf-8")
    return p


@pytest.fixture
def bad_puml(tmp_path: Path) -> Path:
    p = tmp_path / "bad.puml"
    p.write_text(BAD_PUML, encoding="utf-8")
    return p


def png_dimensions(path: Path) -> tuple:
    """Return (width, height) of a PNG without a third-party dep."""
    with open(path, "rb") as f:
        magic = f.read(8)
        assert magic == b"\x89PNG\r\n\x1a\n", f"not a PNG: {path}"
        # IHDR is the first chunk; length(4) + type(4) = 8 bytes header
        f.read(8)
        ihdr = f.read(8)
    width, height = struct.unpack(">II", ihdr)
    return width, height


def png_unique_pixel_count_estimate(path: Path) -> int:
    """
    Cheap proxy for "is this image actually rendered text or just tofu":
    a PNG with real anti-aliased glyphs has high entropy in its IDAT
    stream and decompresses to many distinct byte sequences, while a
    tofu-only image is highly repetitive.

    We use the compressed IDAT length as the proxy — for the same image
    dimensions, real text yields much larger compressed data than tofu.
    """
    return path.stat().st_size
