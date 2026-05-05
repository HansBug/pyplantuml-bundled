# pyplantuml-bundled

[![CI](https://github.com/HansBug/pyplantuml-bundled/actions/workflows/build.yml/badge.svg)](https://github.com/HansBug/pyplantuml-bundled/actions/workflows/build.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3%2B-blue)](LICENSE)
[![Python: 3.6–3.14](https://img.shields.io/badge/python-3.6--3.14-blue)]()
[![PlantUML: 1.2024.7](https://img.shields.io/badge/plantuml-1.2024.7-orange)](https://github.com/plantuml/plantuml)

`pip install pyplantuml-bundled` and you have a working PlantUML — no system Java, no `apt install fontconfig`, no extra fonts. Even on a `python:3.10-slim` or `alpine` container that ships nothing but the Python interpreter, this package renders PlantUML diagrams (including CJK text) out of the box.

![cli demo](docs/img/cli-demo.gif)

## Why this exists

PlantUML is ubiquitous in CI doc-builds, lint hooks, notebook sidecars, and code-review tooling. The standard `plantuml` PyPI package is a thin Python wrapper that shells out to a `java` you have to install yourself. That works on a developer laptop but adds friction to every container, every cloud function, every "just pip install everything" pipeline. This package trades wheel size (≈50–60 MB per platform) for `pip install` ergonomics: one line of dependency, zero system prerequisites, deterministic rendering across Linux glibc, Linux musl, macOS, and Windows.

## What's in the wheel

![architecture](docs/img/architecture.png)

| Component | Source | Per-platform size | License |
|---|---|---|---|
| `plantuml.jar` | upstream PlantUML 1.2024.7 | 22 MB (shared) | GPL-3.0-or-later |
| `jre/` | Eclipse Temurin 17 (Microsoft OpenJDK 17 on Win-ARM64), `jlink`-stripped to the modules PlantUML actually uses | 47–58 MB | GPLv2 + Classpath Exception |
| `runtime/linux-<arch>/lib` | `libfontconfig.so.1` + `libfreetype.so.6` + chain | 1.8 MB (Linux only) | MIT / FTL / various permissive |
| `runtime/linux-<arch>/fonts` | DejaVu Sans + WenQuanYi Micro Hei | 6.4 MB (Linux only) | Bitstream Vera / Apache-2.0 |
| `runtime/fonts.conf.template` | rendered with absolute paths at first run | <1 KB | n/a |
| `__init__.py` | pure-Python launcher / API | 4 KB | GPL-3.0-or-later |

The JRE module set is the empirically minimal set that still renders PNG, SVG, ASCII, and runs `-checkonly`: `java.base, java.desktop, java.xml, java.scripting, java.naming, java.logging, java.management, java.sql, jdk.zipfs, jdk.crypto.ec, jdk.unsupported`.

## Install

```bash
pip install pyplantuml-bundled
```

`pip` selects the right wheel for your OS, architecture, and libc automatically. **One single wheel covers Python 3.6 through 3.14** on the same platform — there are no per-Python-version wheels because the package has no C extensions and the launcher only uses 3.6-compatible stdlib APIs. Wheel tag is `py3-none-{platform}`.

### Pre-built wheel matrix

| Platform | Wheel tag | libc / runtime baseline | Approx. size |
|---|---|---|---|
| Linux x86_64  | `py3-none-manylinux_2_17_x86_64`   | glibc 2.17 (CentOS 7 / Debian 8 era, 2014+) | ~58 MB |
| Linux aarch64 | `py3-none-manylinux_2_17_aarch64`  | glibc 2.17                                  | ~58 MB |
| Linux x86_64  | `py3-none-musllinux_1_1_x86_64`    | musl 1.1 (Alpine 3.12+, 2020+)              | ~55 MB |
| Linux aarch64 | `py3-none-musllinux_1_1_aarch64`   | musl 1.1                                    | ~55 MB |
| macOS x86_64  | `py3-none-macosx_*_x86_64`         | macOS 10.13+ (Intel)                        | ~50 MB |
| macOS arm64   | `py3-none-macosx_*_arm64`          | macOS 11.0+ (Apple Silicon)                 | ~50 MB |
| Windows x86_64 | `py3-none-win_amd64`              | Windows 10+ (x64)                           | ~48 MB |
| Windows arm64  | `py3-none-win_arm64`              | Windows 11 ARM                              | ~48 MB |

### Wheel test matrix (clean-environment stage 2)

Every release runs the wheel through 3 independent phases on a clean distro container — install + selfcheck → external smoketest (5-check black-box) → pytest unit tests — across this OS coverage:

| Family | Distros tested |
|---|---|
| Debian      | `debian:10-slim` (buster, 2019, glibc 2.28) → `debian:12-slim` (bookworm, 2023, glibc 2.36) |
| Ubuntu      | `18.04` (bionic, 2018) → `20.04` (focal, 2020) → `22.04` (jammy, 2022) → `24.04` (noble, 2024) |
| Red Hat     | `rockylinux:8` (EL8, 2019) → `rockylinux:9` (EL9, 2022) → `fedora:40` (2024) |
| Alpine      | `3.10` (2019, musl 1.1.22) → `3.12` (2020, musllinux_1_1 floor) → `3.20` → `3.21` (2024) |
| macOS       | `macos-15-intel` (x86_64) and `macos-14` (arm64) |
| Windows     | `windows-2022` (x86_64) and `windows-11-arm` (arm64) |

20 Linux × 3 phases + 4 mac/win × 3 phases = **24 wheel stage-2 jobs every CI run**.

## Quick start

### CLI

The `plantuml` console script proxies all arguments straight to the bundled `plantuml.jar`:

```bash
plantuml -tpng diagram.puml          # render to PNG
plantuml -tsvg diagram.puml          # render to SVG
plantuml -checkonly diagram.puml     # static check; exit 0 if valid
plantuml -version                    # PlantUML + JRE versions
plantuml -help                       # full upstream CLI options
```

### Python API

```python
from pyplantuml import render, check, version, run, JAR_PATH, JAVA_BIN, PlantUmlError

# Render to a target directory:
render("diagram.puml", fmt="svg", output_dir="out/")

# Static check; True iff the file is syntactically valid:
assert check("diagram.puml")

# Multi-line version string from PlantUML + bundled JRE:
print(version())

# Pass any plantuml.jar arguments through; full subprocess.CompletedProcess back:
proc = run(["-help"], capture_output=True)
print(proc.stdout)

# Locate the bundled binaries (useful for advanced integrations):
print(JAR_PATH)   # …/site-packages/pyplantuml/plantuml.jar
print(JAVA_BIN)   # …/site-packages/pyplantuml/jre/bin/java
```

`render`, `check`, and `run` raise `PlantUmlError` on failure (subclass of `RuntimeError`). Pass `check=False` to `run` to recover from non-zero exits manually.

## CJK rendering

Tofu-free Chinese / Japanese / Korean rendering is a deliberate feature, not an accident. On Linux the wheel ships its own `libfontconfig` chain plus DejaVu (Latin / Cyrillic / Greek) and WenQuanYi Micro Hei (a single `.ttc` covering Simplified Chinese, Traditional Chinese, Japanese kana + common kanji, Korean Hangul). The launcher writes a tiny `fonts.conf` with `<lang>zh|ja|ko</lang>` rules so PlantUML's text layout picks the right family per script.

The example below was rendered from `examples/01_sequence_cjk.puml` inside a `python:3.10-slim` container with no system fonts:

![cjk sequence](docs/img/01_sequence_cjk.png)

On macOS and Windows the wheel relies on the OS-provided font stack (CoreText / GDI), which already ships CJK families (PingFang SC, Microsoft YaHei, Yu Gothic, Malgun Gothic). No extra bundling required there.

## More example diagrams

These all live in `examples/` and are re-rendered as part of every release:

| Diagram | Renders | Source |
|---|---|---|
| `class_diagram.png` | API surface as UML | [`02_class_diagram.puml`](examples/02_class_diagram.puml) |
| `state_machine.png` | `pyplantuml.run()` lifecycle | [`04_state_machine.puml`](examples/04_state_machine.puml) |
| `component_pipeline.png` | The CI build matrix | [`03_component_pipeline.puml`](examples/03_component_pipeline.puml) |

<table>
<tr>
<td><img src="docs/img/class_diagram.png" alt="class diagram" width="100%"/></td>
<td><img src="docs/img/state_machine.png" alt="state machine" width="100%"/></td>
</tr>
</table>

## How it works

1. The Python launcher (`pyplantuml/__init__.py`) locates `plantuml.jar` and the bundled `java` via `Path(__file__).parent`.
2. On Linux it materialises a `fonts.conf` into the user cache dir (default: `~/.cache/pyplantuml/fontconfig/`) with absolute paths to the bundled font directory.
3. It builds an env where `LD_LIBRARY_PATH` is prepended with `runtime/linux-<arch>/lib` and `FONTCONFIG_FILE` points at the rendered `fonts.conf`. macOS and Windows skip this step entirely.
4. `subprocess.run(["…/jre/bin/java", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8", "-jar", JAR_PATH, *args], env=…)` does the actual rendering.

Want to use a different JVM (system Java, GraalVM, etc.) for debugging? Set `PYPLANTUML_JAVA=/path/to/java` and the bundled JRE is bypassed.

## Configuration

| Environment variable | Effect |
|---|---|
| `PYPLANTUML_JAVA` | Override the bundled JRE with an arbitrary `java` executable. |
| `XDG_CACHE_HOME` | Override the location of the rendered `fonts.conf` (Linux only). Defaults to `$HOME/.cache`. |
| `LOCALAPPDATA` | Same as above on Windows. |
| Standard PlantUML env vars (`PLANTUML_LIMIT_SIZE`, `GRAPHVIZ_DOT`, …) | Forwarded to the JVM unchanged. |

## Comparison with related open-source projects

There are several mature PlantUML-related projects in the Python / Docker ecosystem; each makes a different trade-off between install simplicity, network dependency, and rendering control. The table below benchmarks `pyplantuml-bundled` against the most widely used ones — **column headers link to each project's home / repository**, click through for full details:

| Dimension | [pyplantuml-bundled](https://github.com/HansBug/pyplantuml-bundled) (this) | [python-plantuml](https://github.com/dougn/python-plantuml) | [plantweb](https://github.com/kuralabs/plantweb) | [sphinxcontrib-plantuml](https://github.com/sphinx-contrib/plantuml) | [plantuml-markdown](https://github.com/mikitex70/plantuml-markdown) | [IPlantUML](https://github.com/jbn/IPlantUML) | [plantuml-server](https://github.com/plantuml/plantuml-server) |
|---|---|---|---|---|---|---|---|
| **Install** | `pip install` | `pip install` | `pip install` | `pip install` | `pip install` | `pip install` | `docker pull` |
| **System Java needed** | **No** (bundled JRE) | No (uses remote server) | No (uses remote server) | **Yes** (local `java`) | **Yes** for local mode (or remote) | **Yes** (local `plantuml.jar`) | (built into image) |
| **Network at render time** | **No** | **Yes** (defaults to public `plantuml.com` server) | **Yes** (defaults to public server) | No | No (local) / Yes (remote) | No | No (HTTP to local container) |
| **Rendering offline / air-gapped** | ✅ | ❌ unless you run your own server | ❌ unless you run your own server | ✅ | ✅ in local mode | ✅ | ✅ |
| **CJK on bare Linux container** | ✅ (bundled fontconfig + WenQuanYi MicroHei) | depends on the server's fonts | depends on the server's fonts | ❌ unless you `apt install fontconfig fonts-…` | ❌ same | ❌ same | ✅ (image bundles `fonts-wqy-zenhei`) |
| **Per-call latency** | JVM cold-start (~1 s) | HTTP round-trip | HTTP round-trip | JVM cold-start | JVM cold-start | JVM cold-start | HTTP (warm JVM, ~ms) |
| **Approx. footprint** | 50–60 MB / wheel | <100 KB | ~50 KB | <100 KB (+ system JRE) | <100 KB (+ system JRE) | <100 KB (+ jar + JRE) | ~600 MB Docker image |
| **Sweet spot** | CI, sandboxed scripts, single-shot rendering, no-deps environments | Quick prototypes that have internet | Sphinx + ReadTheDocs (pure-Python rendering) | Sphinx doc builds where the build host already has Java | MkDocs / Markdown sites | Jupyter / IPython notebooks | High-throughput interactive editors and servers |

Quick mental model:

- **Network OK + want zero local cost?** Use [`python-plantuml`](https://github.com/dougn/python-plantuml) or [`plantweb`](https://github.com/kuralabs/plantweb).
- **Need offline + already have Java + writing Sphinx docs?** Use [`sphinxcontrib-plantuml`](https://github.com/sphinx-contrib/plantuml).
- **Need offline + zero system prerequisites + reproducible CI?** This package.
- **Rendering thousands of diagrams a minute?** Run [`plantuml-server`](https://github.com/plantuml/plantuml-server) in Docker and POST to it; the persistent JVM amortises start-up cost away.

For high-volume offline rendering inside this package, keep a JVM warm by reusing one `subprocess.Popen` against PlantUML's `-pipe` mode (reads many diagrams off stdin sequentially):

```python
import subprocess, pyplantuml
proc = subprocess.Popen(
    [str(pyplantuml.JAVA_BIN), "-Djava.awt.headless=true",
     "-jar", str(pyplantuml.JAR_PATH), "-pipe", "-tpng"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
)
# write puml source + delimiter to proc.stdin, read PNG bytes back from stdout.
```

## Troubleshooting

**`PlantUmlError: bundled JRE not found at …/jre/bin/java`** — you installed a wheel built for a different platform (e.g. installed `manylinux` wheel on macOS via `--platform`). Reinstall with the right platform tag, or set `PYPLANTUML_JAVA` to a system JVM.

**`Fontconfig warning: … unknown element "reset-dirs"`** — benign. Older bundled `libfontconfig` sees newer system config syntax. Suppress with `2>/dev/null`. Does not affect rendering. To be cleaned up in a future release.

**CJK shows as boxes (tofu) on Linux** — the wheel was *not* built with `runtime/linux-<arch>/` populated (e.g. you built from source and skipped `scripts/stage_linux_runtime.sh`). Run `make assets && pip install --force-reinstall .`.

**Slow first render on Linux** — fontconfig is building its on-disk cache for the bundled fonts. One-time cost, lives at `~/.cache/pyplantuml/fontconfig/`.

**Need GraphViz output (`dot` engine, component / class diagrams with auto-layout)** — install Graphviz separately (`apt install graphviz` / `brew install graphviz`) and PlantUML will pick it up via `$PATH`. Bundling Graphviz is not in scope; it would double the wheel size.

## Portable executables (no Python required)

Beyond the wheel, every release also ships a self-contained PyInstaller-built `plantuml` binary. These embed Python + PlantUML jar + JRE + (Linux only) the fontconfig stack, so you can drop them on a machine that has neither Python nor Java installed and they Just Work. Two flavours per platform — single self-extracting binary (`plantuml-onefile-<plat>`) and a directory archive (`plantuml-onedir-<plat>.zip`) — downloadable from the [GitHub release page](https://github.com/HansBug/pyplantuml-bundled/releases).

> **macOS Apple Silicon caveat**: a portable executable for macos-arm64 is *not* shipped. Apple Silicon's hardened-runtime requires the bundled OpenJDK to hold the `com.apple.security.cs.allow-jit` entitlement, which is only honoured by binaries signed with a paid Developer-ID identity. Ad-hoc-signed binaries (the only option for an OSS project) crash with `SIGSEGV` at `pc=0x0` during JVM init regardless of every workaround we tried (`-Xint`, removing `--options runtime`, embedding the entitlement at build time, etc.). The wheel works fine on macos-arm64 — install with `pip install pyplantuml-bundled`.

```bash
curl -LO https://github.com/HansBug/pyplantuml-bundled/releases/latest/download/plantuml-onefile-linux-x86_64-glibc
chmod +x plantuml-onefile-linux-x86_64-glibc
./plantuml-onefile-linux-x86_64-glibc -tpng diagram.puml
./plantuml-onefile-linux-x86_64-glibc selfcheck   # 28-case diagnostic
```

### Pre-built portable executable matrix

| Platform | Onefile binary | Onedir archive | Build container baseline |
|---|---|---|---|
| Linux x86_64 glibc  | `plantuml-onefile-linux-x86_64-glibc`  | `plantuml-onedir-linux-x86_64-glibc.zip`  | Debian 10 buster (glibc 2.28, 2019) |
| Linux aarch64 glibc | `plantuml-onefile-linux-aarch64-glibc` | `plantuml-onedir-linux-aarch64-glibc.zip` | Debian 10 buster (glibc 2.28)       |
| Linux x86_64 musl   | `plantuml-onefile-linux-x86_64-musl`   | `plantuml-onedir-linux-x86_64-musl.zip`   | Alpine 3.12 (musl 1.1.24, 2020)     |
| Linux aarch64 musl  | `plantuml-onefile-linux-aarch64-musl`  | `plantuml-onedir-linux-aarch64-musl.zip`  | Alpine 3.12                          |
| macOS x86_64        | `plantuml-onefile-macos-x86_64`        | `plantuml-onedir-macos-x86_64.zip`        | macos-15-intel runner (Python 3.10) |
| macOS arm64         | _not shipped — see hardened-runtime caveat above_ | — | — |
| Windows x86_64      | `plantuml-onefile-windows-x86_64.exe`  | `plantuml-onedir-windows-x86_64.zip`      | windows-2022 runner (Python 3.10)   |
| Windows arm64       | `plantuml-onefile-windows-arm64.exe`   | `plantuml-onedir-windows-arm64.zip`       | windows-11-arm runner (Python 3.11) |

### Portable test matrix (clean-environment stage 2)

CI exercises every (onefile, onedir) artifact through the same 3 independent phases as the wheel matrix — fresh distro container selfcheck → external 5-check smoketest (no python, no java; only the binary runs) → pytest unit tests over the binary via subprocess — across this OS coverage:

| Family | Distros tested |
|---|---|
| Debian      | `debian:10-slim` (buster, glibc 2.28 floor) → `debian:12-slim` (bookworm) |
| Ubuntu      | `20.04` (focal) → `22.04` (jammy) → `24.04` (noble). _No 18.04: glibc 2.27 is below the portable build container's 2.28 floor; install via wheel on bionic._ |
| Red Hat     | `rockylinux:8` (EL8) → `rockylinux:9` (EL9) → `fedora:40` (rolling) |
| Alpine      | `3.10` (2019, musl 1.1.22) → `3.12` (2020, baseline) → `3.20` → `3.21` (2024) |
| macOS       | `macos-15-intel` (x86_64) — _no arm64, see caveat_ |
| Windows     | `windows-2022` (x86_64) and `windows-11-arm` (arm64) |

22 Linux × 3 phases × 2 artifacts (onefile + onedir) + 3 mac/win × 3 phases × 2 artifacts = **25 portable stage-2 jobs every CI run**.

The "clean container" guarantee is real: the selfcheck and smoketest phases install **nothing** inside the container — the binary is the only thing that runs. The pytest phase installs python3 + pytest only; java/jdk are never present (the binary's bundled JRE is what java calls land on).

## Self-check (`plantuml selfcheck`)

`plantuml selfcheck` is the diagnostic of last resort: 28 isolated cases that together prove every Python-side and bundled-asset surface still works on the running machine. Each case is wrapped in a `BaseException` catch so the runner finishes even when half the install is broken; output is ANSI-colored PASS/FAIL rows with the offending traceback and a one-line remediation hint per failure.

Cases cover, in order: Python runtime + critical stdlib, the `click` Python dep (`CliRunner` round-trip on a stub command), package layout (jar zip signature, JRE module set, Linux runtime tree, fonts staged), bundled native libs (`ctypes.CDLL` + `FcInit` for libfontconfig, `FT_Init_FreeType` for libfreetype), font signatures (TTF / TTC magic bytes), runtime probes (`java -version`, cache-dir writability, `pyplantuml.version()` banner), end-to-end rendering (PNG / SVG / `-checkonly`), CJK rendering byte-size + width visual proxy, network-blocked offline render, and the PyInstaller `_MEIPASS` layout when running frozen.

```bash
plantuml selfcheck                  # full report with environment dump
plantuml selfcheck --no-env         # skip environment dump (faster)
plantuml selfcheck --no-color       # disable ANSI colour
plantuml selfcheck --color          # force colour even on non-TTY (CI logs)
```

Exit code is the count of failed cases (0 when clean).

## Building from source

```bash
git clone https://github.com/HansBug/pyplantuml-bundled
cd pyplantuml-bundled

# Requires JDK 17 with the jmods directory (e.g. Eclipse Temurin 17).
export JAVA_HOME=/path/to/jdk17

make assets               # fetch jar, jlink JRE, stage Linux native libs
python -m build --wheel   # emits dist/pyplantuml_bundled-*.whl
pip install pytest dist/*.whl
pytest tests/             # render PNG/SVG, CJK byte-size, etc.

# Portable executable (onefile + onedir.zip)
pip install pyinstaller click
bash scripts/pyinstaller/build.sh
ls pyinstaller-dist/
```

For the multi-platform CI see [`.github/workflows/build.yml`](.github/workflows/build.yml) (wheels via `cibuildwheel`) and [`.github/workflows/portable.yml`](.github/workflows/portable.yml) (PyInstaller binaries with stage-1 build + stage-2 clean-env validation).

## License

GPL-3.0-or-later, inherited from PlantUML upstream. The full text of every redistributed binary's license lives in [`NOTICE`](NOTICE) and inside the bundled `plantuml.jar` itself under `META-INF/`.

## Versioning

The package version is `<plantuml-version>.<wrapper-revision>` — the first three segments mirror the bundled `plantuml.jar` (e.g. `1.2024.7`), and the trailing segment is bumped on wrapper-only fixes (CI matrix, staging script, click compatibility, new platform support) without an upstream PlantUML change. So `1.2024.7.1` means PlantUML 1.2024.7 plus this project's first wrapper revision. The bundled upstream version is also exposed as `pyplantuml.__plantuml_version__`. Tag a new commit `vX.Y.Z.W` to trigger a fresh CI release.
