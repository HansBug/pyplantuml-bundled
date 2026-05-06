# AGENTS.md — guidance for AI coding agents working on this repo

This file is the canonical spec for any AI agent (Claude Code, Codex, Cursor, Aider, etc.) operating on `pyplantuml-bundled`. `CLAUDE.md` is a symlink to this file, so Claude Code reads the same content.

## What this project is

A PyPI distribution that lets people `pip install pyplantuml-bundled` and get a fully self-contained PlantUML CLI + Python API. The wheel embeds:

- `plantuml.jar` from upstream PlantUML.
- A `jlink`-stripped OpenJDK 11 JRE (per-platform native bits). 11 is the lowest functional version that still renders all PlantUML diagram types — anything older lacks `java.desktop` modules PlantUML relies on.
- On Linux, the fontconfig + freetype + harfbuzz + glib + pcre + brotli native chain plus DejaVu and WenQuanYi Micro Hei fonts so CJK renders inside scratch / slim containers that have nothing pre-installed.

## Hard constraints

1. **The wheel must work on a clean container with NO Java and NO fontconfig.** Stage 2 of CI validates this on 20+ Linux base images (debian, ubuntu, rocky, fedora, alpine, oldest-to-newest within each family) plus macOS and Windows runners. Any new dependency must come bundled or work without it.
2. **CJK rendering must be visually correct, not just "doesn't crash".** Tofu / square-box glyphs do not raise errors — every test path must either inspect pixels or assert PNG byte-size against a sane lower bound (≥4 KB for the small fixture, ≥8 KB for non-trivial CJK content) AND a sane minimum width (PlantUML lays out boxes to text width; tofu collapses it).
3. **Wheel tag is `py3-none-<platform>`.** The package has no C extensions. `setup.py` overrides `bdist_wheel` to force this tag so one wheel works on Python 3.6 through 3.14. CI sets `PYPLANTUML_PLAT_TAG` to the right manylinux/musllinux baseline so pip rejects the wheel on incompatible distros.
4. **No GPL incompatibility.** The whole project inherits PlantUML's GPL-3.0-or-later. Do not add code under license terms incompatible with GPLv3. Bundled binaries each keep their own license; `NOTICE` tracks them.
5. **Linux runtime libraries (`libfontconfig.so` etc.) must be staged from the same manylinux/musllinux container that builds the wheel.** Do not stage from a Debian image and ship into a manylinux wheel — the glibc baseline mismatch will explode at import time on older distros.
6. **`tests/` and `tests_portable/` are real Python modules** (each with `__init__.py`). Tests use `from .conftest import …` rather than relying on pytest's rootdir-injection magic, so the layout is portable across `pytest`, `python -m pytest`, and CI's mounted-into-container runs.

## Compatibility floors

| Surface | Floor | Why |
|---|---|---|
| Python (wheel runtime) | 3.6 | Lowest still-encountered Python on long-lived prod boxes (Ubuntu 18.04 ships 3.6.9). The wheel itself is `py3-none`, so a single artifact serves 3.6–3.14. |
| Python (PyInstaller build-time) | 3.6 (Linux, both archs) / 3.7 (mac-x86_64 + win-x86_64) / 3.11 (win-arm64) | PyInstaller embeds the build-time interpreter into the binary. Lower build-time Python = wider runtime compat for the portable exe. mac/win-x86_64 use 3.7 because `actions/setup-python` no longer caches 3.6 on those slots; win-arm64 has no 3.7 build, 3.11 is the lowest available. |
| Linux glibc (wheel) | 2.17 (`manylinux_2_17`) | CentOS 7 / RHEL 7 / Debian 8 / Ubuntu 14.04+ era, 2014-and-newer. Lower than `_2_28` to keep the supported window wide. |
| Linux musl (wheel) | 1.1 (`musllinux_1_1`) | Alpine 3.12+ (2020). Lower than `_1_2` to include long-lived 3.12-based prod images. |
| Linux glibc (portable) | 2.28 (Debian 10 buster) | The PyInstaller build container's glibc is the binary's lower bound. Ubuntu 18.04 (glibc 2.27) is **below** this and intentionally not in the portable matrix — install via wheel there. |
| Linux musl (portable) | 1.1.24 (Alpine 3.12) | Same logic — the build-time alpine image dictates the floor. |
| macOS arm64 portable | _not shipped_ | Apple Silicon's hardened-runtime requires the embedded OpenJDK to hold `com.apple.security.cs.allow-jit`, only honored by paid-Developer-ID-signed binaries. Ad-hoc-signed binaries crash with `SIGSEGV pc=0x0` during JVM init regardless of every workaround (`-Xint`, removing `--options runtime`, embedding the entitlement at build, etc.). The wheel works fine on macos-arm64.

These floors are **load-bearing** — every CI matrix entry is chosen to be at or above the corresponding floor, and stage-2 tests across multiple distro versions guard against regressions.

## Layout

```
.
├── src/pyplantuml/
│   ├── __init__.py          – launcher / public API
│   ├── _click_cli.py        – click-based CLI (with plantuml.jar passthrough)
│   ├── diagnostics.py       – plantuml selfcheck case definitions
│   ├── plantuml.jar         – fetched by scripts/, gitignored
│   ├── jre/                 – built by scripts/, gitignored
│   └── runtime/
│       ├── fonts.conf.template  – committed, has {FONT_DIR}/{CACHE_DIR} placeholders
│       └── linux-<arch>/
│           ├── lib/         – staged by scripts/ at CI time, gitignored
│           └── fonts/       – staged by scripts/ from vendored/ at CI time, gitignored
├── vendored/fonts/          – committed (DejaVu + WenQuanYi MicroHei TTC)
├── scripts/
│   ├── fetch_plantuml_jar.sh         – sha256-verified jar download (PLANTUML_VERSION + PLANTUML_SHA256 env-overridable)
│   ├── build_jre.sh                  – jlink minimal JRE from $JAVA_HOME (OpenJDK 11)
│   ├── stage_linux_runtime.sh        – .so chain + fonts staging into wheel (manylinux/musllinux only)
│   ├── stage2_install_python.sh      – CI helper: install python3+pip in any distro container
│   ├── stage2_install_wheel.sh       – CI helper: stage2_install_python.sh + pip install wheel
│   ├── portable_smoketest.sh         – CI helper: 5-check black-box smoketest of any plantuml binary
│   ├── bump_plantuml_version.sh      – switch repo to a target plantuml version (rewrites pyproject/__init__/CHANGELOG/README/fetch script + new sha256)
│   └── pyinstaller/                  – portable exe spec + entry script
├── tests/                   – pyplantuml Python API tests (used by wheel pytest)
├── tests_portable/          – subprocess-based tests of the portable binary
├── .github/workflows/
│   ├── build.yml            – wheel build + 3-phase stage 2 + release-only PyPI/Release publish
│   ├── portable.yml         – portable exe build + 3-phase stage 2 + release-only Release publish
│   ├── unit-test.yml        – fast Linux py3.10/3.11/3.12 pytest, push/PR feedback loop
│   └── watch-upstream-release.yml – manual dispatch (schedule off): detects new plantuml/plantuml release, opens bump PR
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
2. `scripts/build_jre.sh` → `src/pyplantuml/jre/` (uses `$JAVA_HOME` / jlink, OpenJDK 11)
3. `scripts/stage_linux_runtime.sh` → `src/pyplantuml/runtime/linux-<arch>/` (Linux only; macOS / Windows skip)
4. `python -m build --wheel` → `dist/pyplantuml_bundled-*-py3-none-<plat>.whl` (or PyInstaller for portable)
5. Stage-2 tests against the produced artifact in clean containers (see below)

## CI matrix

Two workflows: `build.yml` (wheels, 8 build matrix entries) and `portable.yml` (PyInstaller binaries, 7 build matrix entries — no macos-arm64). Both use the same 3-phase stage-2 testing model.

Each wheel/portable build runs `cibuildwheel` (wheel) or PyInstaller (portable) on the appropriate runner with `OpenJDK 11`. Wheel build runners use `manylinux2014` / `musllinux_1_1` containers for Linux; portable Linux uses `python:3.6-slim-buster` / `python:3.6-alpine3.12`.

Stage-2 distros tested (oldest → newest within each family):

| Family | Wheel covers | Portable covers |
|---|---|---|
| Debian | 10-slim, 12-slim (× 2 archs) | 10-slim, 12-slim (× 2 archs) |
| Ubuntu | 18.04, 20.04, 22.04, 24.04 (aarch64 from 20.04) | 20.04, 22.04, 24.04 (× 2 archs each) — _no 18.04, glibc floor_ |
| Red Hat | rockylinux:8, rockylinux:9, fedora:40 (x86_64) | rockylinux:8, rockylinux:9, fedora:40 (× 2 archs) |
| Alpine | 3.10, 3.12, 3.20, 3.21 (aarch64 from 3.20) | 3.10, 3.12, 3.20, 3.21 (aarch64 from 3.20) |
| macOS | x86_64 + arm64 | x86_64 only |
| Windows | x86_64 + arm64 | x86_64 + arm64 |

Stage-2 uses **bare distro images only** (`debian:*`, `ubuntu:*`, `rockylinux:*`, `fedora:*`, `alpine:*`) — never `python:*` or other language-prebuilt images. The whole point of stage 2 is "user runs `pip install` on a fresh distro and it works", so python must come from the distro's own package manager.

## Stage-2 testing model (3 phases per matrix entry)

Both wheel and portable stage-2 run the artifact through three independent phases in three independent docker containers:

1. **selfcheck** — install python3 + the artifact (wheel: install wheel; portable: just `cp` the binary), run `plantuml selfcheck`. The diagnostic battery is the product's own self-test.
2. **external smoketest** — fresh container, install the artifact, run `scripts/portable_smoketest.sh` against the resulting `plantuml` command. Five black-box checks: `-version` banner / `-tpng` PNG header / `-tsvg` SVG structure / `-checkonly` exit code / CJK PNG byte size. **No python or pytest in this phase**, just shell + the binary. This is the "external user perspective" check.
3. **pytest** — fresh container, install python3 + pytest + the artifact, run unit tests. Wheel uses `tests/` (Python API tests). Portable uses `tests_portable/` (subprocess-based tests over the binary — no Python API import, the binary itself is the unit under test).

"Clean container" guarantees:

- **Portable** selfcheck and smoketest install **nothing** in the container — the binary is the only thing that runs. The pytest phase installs python3 + pytest only; java/jdk are never present (the binary's bundled JRE is what java calls land on).
- **Wheel** stage 2 always installs python3 because `pip install` needs it; jdk is never installed because the wheel ships its own JRE.

`scripts/stage2_install_python.sh` and `scripts/stage2_install_wheel.sh` are the install helpers — they encode the apk / dnf / yum / apt branching, debian-buster archive rewrite, ubuntu apt-mirror rewrite, and pip bootstrap once and are mounted into every test container.

## Linux runtime staging — the SONAME maze

`scripts/stage_linux_runtime.sh` is the trickiest part of this repo. It runs **inside** the manylinux/musllinux build container, copies the `.so` chain that PlantUML's bundled JRE will dlopen at runtime, and ships them inside `runtime/linux-<arch>/lib/`.

**The dependency chain is**: `libfontmanager.so` (in jlink-built JRE) → `libfreetype.so` + `libharfbuzz.so`. On glibc-built `harfbuzz` (CentOS / Debian / Ubuntu) `libharfbuzz.so` further pulls in `libglib-2.0.so.0` → `libpcre.so`. On musl (Alpine) `harfbuzz` is built without the glib backend so glib/pcre are not transitive. **Every link in this chain must be in the wheel.**

**SONAMEs drift between build containers.** The same upstream library has different `.so` names on different distros:

| Library | manylinux2014 (CentOS 7) | musllinux_1_1 (Alpine 3.12) | python:3.6-slim-buster (Debian 10) |
|---|---|---|---|
| libpng | `libpng15.so.15` (1.5) | `libpng16.so.16` (1.6) | `libpng16.so.16` (1.6) |
| libpcre | `libpcre.so.1` (PCRE 8) | `libpcre.so.1` | `libpcre.so.3` (Debian's own SONAME for PCRE 8) |

The staging script uses **alt-SONAME groups** (`libpng16.so.16|libpng15.so.15`) — for each group it copies the first one that exists in the build container. Whatever the container has is what `libfreetype` / `libharfbuzz` linked against, so the runtime loader will ask for that exact name. **Do not collapse this to a single SONAME** without careful reasoning.

**Other Linux staging gotchas**:

- **CentOS 7 aarch64 vault is missing `brotli`** (only x86_64 has it). The `_install_optional` helper installs each optional package independently with `|| skip`, so a missing one doesn't abort the whole pre-stage. The graceful "could not locate any of [...] — skipping" branch in the copy loop then handles musl-only packages similarly.
- **Pre-usrmerge Debian/Ubuntu** (Debian 10/11 era) keep some shared libraries under `/lib/<triplet>` rather than `/usr/lib/<triplet>`. `libpcre3:arm64` on debian-buster lives at `/lib/aarch64-linux-gnu/libpcre.so.3`. `SEARCH_DIRS` in the stage script must include both `/usr/lib/<triplet>` and `/lib/<triplet>` for x86_64 + aarch64, glibc + musl.
- `libglib-2.0.so.0` was discovered as a hidden dep only after stage 2 caught `java.lang.UnsatisfiedLinkError: libglib-2.0.so.0: cannot open shared object file` on debian-slim / ubuntu (which don't pre-install libglib2.0-0). It was already pulled in transitively on the build host, so wheel build looked fine; only stage 2 against a bare image surfaced the gap.

## Click CLI integration — two non-obvious patches

`src/pyplantuml/_click_cli.py` does two things that are easy to remove without realising they are load-bearing:

1. **Click 7.x ASCII-locale neutralization.** Click 7.x's `_unicodefun._verify_python3_env` raises `RuntimeError` on container startup when `LANG`/`LC_ALL` are unset — a default state on debian-slim / ubuntu / alpine without locale data. Click 8.1.0 removed this check (issue pallets/click#2198) but Python 3.6 is pinned to click 7.x. The fix monkey-patches `_verify_python3_env` to a no-op on **both** `click._unicodefun` *and* `click.core` — the latter has captured its own reference via `from ._unicodefun import _verify_python3_env` at import time, so patching only the source module has no effect.
2. **plantuml.jar single-dash flag passthrough.** Click cannot parse single-dash multi-letter tokens (`-version`, `-help`, `-tpng`, `-checkonly`, `-tsvg`, …). They are plantuml.jar's native CLI grammar but are neither short option nor long option from click's POV. Click falls through to subcommand lookup and aborts with `Error: No such command '-version'`. `main()` detects this case before `cli.main()` runs and forwards the full argv straight to the bundled jar via `_run()`. **Subcommands** (`info`, `selfcheck`) and **click's own flags** (`-h` / `-V` / `--help` / `--version-pyplantuml`) bypass the bypass.

## Python 3.6 compat checklist

The portable executable's embedded interpreter is built on Python 3.6 (lowest floor for max runtime compat), so source code reachable from the entry point cannot use:

- `from __future__ import annotations` (PEP 563, 3.7+) — raises SyntaxError on 3.6.
- `@dataclass` (3.7+) — use the `_dataclass_like` decorator in `diagnostics.py` which preserves `__repr__` / `__eq__` / `__hash__`.
- `subprocess.run(..., capture_output=True, text=True)` (3.7+) — spell out `stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True`.
- `dict | dict` (3.9+) merge syntax — use `{**a, **b}`.
- `list[T]` / `dict[K, V]` PEP 585 builtin generics (3.9+) — use `typing.List[T]` / `typing.Dict[K, V]` if needed, but mostly we just don't annotate.

Tests in `tests/` and `tests_portable/` follow the same constraint — they run inside ubuntu:18.04 stage 2 jobs against the system python 3.6.9.

## Cross-platform packaging gotchas

- **Windows venv pip self-upgrade protection.** Inside a venv on Windows, plain `pip install --upgrade pip` fails with "ERROR: To modify pip, please run … python.exe -m pip …". The pip.exe wrapper cannot overwrite itself while running. Always invoke as `python -m pip install --upgrade pip` on Windows venvs.
- **Windows git-bash `command -v plantuml` returns the path without `.exe`.** PATHEXT is a cmd.exe concept, not a sh concept, so `sh "$PLANTUML"` cannot launch the resulting `.../Scripts/plantuml`. Use `python -c "import shutil; print(shutil.which('plantuml'))"` — `shutil.which` honors PATHEXT on windows and returns the binary path unchanged on mac/linux. This is what the wheel mac/win stage-2 jobs do.
- **Debian 10 buster (and earlier) is past LTS EOL** — `deb.debian.org` no longer serves it. The portable build container *and* every stage-2 docker invocation that pulls a buster image needs `sed -i s|deb.debian.org|archive.debian.org|` on `/etc/apt/sources.list` and `Acquire::Check-Valid-Until "false";` in `apt.conf.d/`, before any `apt-get update`. Same logic for stretch (Debian 9). Encoded in `scripts/stage2_install_python.sh`.
- **Ubuntu apt mirror rewrite is ubuntu-container-only.** GitHub runners' `HOST_MIRROR` is an ubuntu-flavored Azure mirror; rewriting a debian container's sources to point at it produces 404s. Stage-2 only rewrites when `/etc/os-release`'s `ID=ubuntu`.

## selfcheck design principle — test real product behavior, not implementation details

`pyplantuml selfcheck` is the diagnostic battery. Its 28 cases follow one rule: **test what the user actually does**, not what the code does internally.

- ✅ **Keep**: `render_png` / `render_svg` / `cjk_png_size` / `render_offline` / `checkonly_valid` — these are end-to-end product behaviour. If they pass, the product works.
- ✅ **Keep**: `libfontconfig_chain` / `libfreetype_chain` — these run `ldd` against the staged libraries with augmented `LD_LIBRARY_PATH`. Stable and useful at build-time triage when staging missed a SONAME.
- ❌ **Removed (used to be there)**: `libfontconfig_loadable` / `libfreetype_loadable` — these did `ctypes.CDLL` + `FcInit()` / `FT_Init_FreeType` from the Python interpreter. They tested whether the *Python* interpreter's already-frozen `LD_LIBRARY_PATH` could dlopen the chain — an implementation detail no real user exercises (java spawned as a subprocess loads its own libfontmanager via its own LD_LIBRARY_PATH that the launcher sets). They were SONAME-fragile (manylinux ships libpng15, debian ships libpng16) and produced false positives even when every render case passed.

When adding a new selfcheck case, ask: "if this case fails but every render case passes, is the product actually broken from the user's POV?" If no, the case is testing an implementation detail and probably shouldn't exist.

## Markdown style

- **Do not hard-wrap paragraphs** in `README.md`, `AGENTS.md`, `NOTICE`, or any other `.md` documentation file. Markdown renders without a max-width cap; pre-wrapping at ~80 columns produces ragged sentences in the rendered output and inflates diffs whenever wording changes. Write each paragraph as a single long line and let the renderer flow it.
- Hard-wrap is fine for code blocks and for command lines that genuinely span multiple shell tokens.

## Iteration discipline

- **Fix the root cause, never wallpaper over a CI failure.** If a test fails because a font is missing, fix the staging step, not the assertion. If a test fails because of an old python compat issue, fix the source to be 3.6-compatible, do not skip the test.
- **`skip` is not an alternative — provide an actual alternative.** When a target environment can't run the original test (e.g. portable can't run on a container below its glibc floor), the matrix should drop that entry with a comment explaining *why*, and other targets should cover the equivalent functionality. Do not add a `skip` annotation that silently green-lights a gap.
- **CI / build / packaging errors: search the open web first.** Distro-specific repo / package / SONAME / EOL-archive issues have almost always been hit by someone publicly. A 30-second web search beats five push-and-watch cycles. Reference the source (issue link, changelog) in the commit message so the next person doesn't have to rediscover.
- **After any non-trivial CI change push immediately and watch the run** rather than guessing locally — CI environments differ from dev hosts in subtle ways (different glibc, different python, missing packages, EOL'd repos).
- **Commits should be reviewable**: do not stuff jar / jre / .so binaries into git — `.gitignore` keeps the repo lean. Vendored fonts (~6 MB total) are an explicit exception because they're small, stable, and platform-independent.
- **When working as `HansBug`** use `GH_TOKEN=$(gh auth token --user HansBug) gh <subcommand>`. Never `gh auth switch` — it disrupts the developer's other workflows. Push uses the SSH remote (configured in `.git/config`) so OAuth workflow-scope dance is unnecessary.
