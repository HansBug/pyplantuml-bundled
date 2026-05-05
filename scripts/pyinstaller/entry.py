"""
Entry point for the PyInstaller-built ``plantuml`` executable.

Kept as a thin shim so the actual CLI lives in ``pyplantuml._click_cli``
and is shared between the wheel and the frozen build. The shim only
exists because PyInstaller wants a real ``__main__``-style file to
build the stub from.
"""
import sys


def main() -> int:
    from pyplantuml import _cli
    return _cli()


if __name__ == "__main__":
    raise SystemExit(main())
