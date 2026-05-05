# AGENTS.md — guidance for AI coding agents working on this repo

This file is the canonical spec for any AI agent (Claude Code, Codex, Cursor, Aider, etc.) operating on `pyplantuml-bundled`. `CLAUDE.md` is a symlink to this file, so Claude Code reads the same content.

## What this project is

A PyPI distribution that lets people `pip install pyplantuml-bundled` and get a fully self-contained PlantUML CLI + Python API. The wheel embeds:

- `plantuml.jar` from upstream PlantUML.
- A `jlink`-stripped Eclipse Temurin 17 JRE (per-platform native bits).
- On Linux, the fontconfig + freetype native chain plus DejaVu and WenQuanYi Micro Hei fonts so CJK renders inside scratch / slim containers that have nothing pre-installed.

## Hard constraints

1. **The wheel must work on a clean container with NO Java and NO fontconfig.** Validate with `python:3.10-slim` (Debian-based) and `python:3.10-alpine` (musl) at minimum.
2. **CJK rendering must be visually correct, not just "doesn't crash".** Tofu / square-box glyphs do not raise errors — every test path must either inspect pixels or assert PNG byte-size against a sane lower bound (≥8 KB for a non-trivial CJK render) AND a sane minimum width (PlantUML lays out boxes to text width; tofu collapses it).
3. **Wheel tag is `py3-none-<platform>`.** The package has no C extensions. `setup.py` overrides `bdist_wheel` to force this tag so one wheel works on Python 3.7 through 3.14. CI sets `PYPLANTUML_PLAT_TAG` to the right manylinux/musllinux baseline so pip rejects the wheel on incompatible distros.
4. **No GPL incompatibility.** The whole project inherits PlantUML's GPL-3.0-or-later. Do not add code under license terms incompatible with GPLv3. Bundled binaries each keep their own license; `NOTICE` tracks them.
5. **Linux runtime libraries (`libfontconfig.so` etc.) must be staged from the same manylinux/musllinux container that builds the wheel.** Do not stage from a Debian image and ship into a manylinux wheel — the glibc baseline mismatch will explode at import time on older distros.
6. **`tests/` is a real Python module** (with `__init__.py`). Tests `from .conftest import …` rather than relying on pytest's rootdir-injection magic. This keeps the test layout portable across `pytest`, `python -m pytest`, and cibuildwheel's CIBW_TEST_COMMAND.

## Layout

```
.
├── src/pyplantuml/
│   ├── __init__.py          – launcher / public API
│   ├── plantuml.jar         – fetched by scripts/, gitignored
│   ├── jre/                 – built by scripts/, gitignored
│   └── runtime/
│       ├── fonts.conf.template  – committed, has {FONT_DIR}/{CACHE_DIR} placeholders
│       └── linux-<arch>/
│           ├── lib/         – staged by scripts/ at CI time, gitignored
│           └── fonts/       – staged by scripts/ from vendored/ at CI time, gitignored
├── vendored/fonts/          – committed (DejaVu + WenQuanYi MicroHei TTC)
├── scripts/
│   ├── fetch_plantuml_jar.sh
│   ├── build_jre.sh
│   └── stage_linux_runtime.sh
├── tests/                   – real Python module, used both locally and as CIBW_TEST_COMMAND
├── .github/workflows/build.yml
├── pyproject.toml
├── setup.py                 – ONLY for `bdist_wheel` tag override
├── MANIFEST.in
├── LICENSE                  – GPLv3 (verbatim from PlantUML upstream)
├── NOTICE                   – bundled-binary attribution
├── README.md
├── AGENTS.md
└── CLAUDE.md  →  AGENTS.md  (symlink)
```

## Build flow (CI mirrors local)

1. `scripts/fetch_plantuml_jar.sh` → `src/pyplantuml/plantuml.jar` (sha256 verified)
2. `scripts/build_jre.sh` → `src/pyplantuml/jre/` (uses `$JAVA_HOME` / jlink)
3. `scripts/stage_linux_runtime.sh` → `src/pyplantuml/runtime/linux-<arch>/` (Linux only; macOS / Windows skip)
4. `python -m build --wheel` → `dist/pyplantuml_bundled-*-py3-none-<plat>.whl`
5. `pytest tests/` → smoke + render PNG/SVG + CJK byte-size + width sanity

## CI matrix (cibuildwheel)

`.github/workflows/build.yml` uses `cibuildwheel` to build one wheel per (OS, arch, libc). Targets:

| Job                   | runner            | container / extra |
|-----------------------|-------------------|-------------------|
| linux x86_64 manylinux | ubuntu-22.04      | manylinux_2_28    |
| linux x86_64 musllinux | ubuntu-22.04      | musllinux_1_2     |
| linux aarch64 manylinux| ubuntu-22.04-arm  | manylinux_2_28    |
| linux aarch64 musllinux| ubuntu-22.04-arm  | musllinux_1_2     |
| macOS x86_64           | macos-13          | (native, setup-java Temurin 17) |
| macOS arm64            | macos-14          | (native, setup-java Temurin 17) |
| windows x86_64         | windows-2022      | (native, setup-java Temurin 17) |

Because we have NO C extensions cibuildwheel only builds with one Python (`CIBW_BUILD=cp310-*`) per matrix entry; `setup.py` retags to `py3-none-<plat>` so the produced wheel is universal across Python 3.7 through 3.14 on the same platform. CIBW_REPAIR_WHEEL_COMMAND is set to a plain `cp` to disable auditwheel/delocate — those tools would fight our manual `LD_LIBRARY_PATH`-based loading model and try to bundle .so deps a second time.

## Markdown style

- **Do not hard-wrap paragraphs** in `README.md`, `AGENTS.md`, `NOTICE`, or any other `.md` documentation file. Markdown renders without a max-width cap; pre-wrapping at ~80 columns produces ragged sentences in the rendered output and inflates diffs whenever wording changes. Write each paragraph as a single long line and let the renderer flow it.
- Hard-wrap is fine for code blocks and for command lines that genuinely span multiple shell tokens.

## Iteration discipline

- Fix the **root cause**, never wallpaper over a CI failure. If a test fails because a font is missing, fix the staging step, not the assertion.
- After any non-trivial CI change push immediately and `gh run watch` rather than guessing locally — CI environments differ from dev hosts in subtle ways.
- Commits should be reviewable: do not stuff jar / jre / .so binaries into git — `.gitignore` keeps the repo lean. Vendored fonts (~6 MB total) are an explicit exception because they're small, stable, and platform-independent.
- When working as `HansBug` use `GH_TOKEN=$(gh auth token --user HansBug) gh <subcommand>`. Never `gh auth switch` — it disrupts the developer's other workflows.
