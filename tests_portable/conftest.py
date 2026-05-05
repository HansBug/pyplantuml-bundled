"""
Pytest fixtures for the portable-binary integration tests.

These tests run a single shell command — the portable plantuml binary —
as a subprocess and verify its output.  No Python API is exercised
(portable executables ship a self-contained Python interpreter inside
the binary, so they have no importable ``pyplantuml`` module from the
runner's point of view).

The binary path is read from the ``PLANTUML`` environment variable;
this is the same convention the smoketest shell script uses, which
keeps the harness symmetric across the two test suites.
"""
import os
import subprocess
from pathlib import Path

import pytest


def _plantuml_path():
    p = os.environ.get("PLANTUML")
    if not p:
        pytest.fail("$PLANTUML must be set to the portable binary path")
    plantuml = Path(p)
    if not plantuml.exists():
        pytest.fail("PLANTUML={!r} does not exist".format(p))
    return plantuml


@pytest.fixture(scope="session")
def plantuml():
    return _plantuml_path()


@pytest.fixture
def simple_puml(tmp_path):
    p = tmp_path / "simple.puml"
    p.write_text(
        "@startuml\nAlice -> Bob : hello\nBob --> Alice : hi\n@enduml\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def cjk_puml(tmp_path):
    p = tmp_path / "cjk.puml"
    p.write_text(
        "@startuml\n"
        "title 中文标题：测试\n"
        "A -> B : 你好世界\n"
        "B --> A : こんにちは\n"
        "@enduml\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def bad_puml(tmp_path):
    p = tmp_path / "bad.puml"
    p.write_text(
        "@startuml\nAlice -> @@@@ broken syntax\n@enduml\n",
        encoding="utf-8",
    )
    return p


def run_plantuml(plantuml, *args, **kwargs):
    """Run the portable binary, capture stdout+stderr, return CompletedProcess.

    Uses ``stdout=PIPE/stderr=PIPE/universal_newlines=True`` rather than
    ``capture_output=/text=`` so this runs on Python 3.6 as well as 3.7+.
    """
    timeout = kwargs.pop("timeout", 120)
    return subprocess.run(
        [str(plantuml)] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
        **kwargs,
    )
