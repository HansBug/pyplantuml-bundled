# pyplantuml-bundled

[![CI](https://github.com/HansBug/pyplantuml-bundled/actions/workflows/build.yml/badge.svg)](https://github.com/HansBug/pyplantuml-bundled/actions/workflows/build.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3%2B-blue)](LICENSE)
[![Python: 3.7–3.14](https://img.shields.io/badge/python-3.7--3.14-blue)]()

`pip install pyplantuml-bundled` and you have a working PlantUML. No system Java required, no extra fonts to install, no `apt install fontconfig` incantations even on `python:slim` or scratch-style containers.

The wheel ships PlantUML ([plantuml/plantuml](https://github.com/plantuml/plantuml)) jar, a minimal JRE built with `jlink` from Eclipse Temurin 17 (~50 MB per platform — only the modules PlantUML actually needs), and on Linux the fontconfig + freetype native stack plus a curated set of fonts (DejaVu + WenQuanYi Micro Hei) so CJK / Cyrillic / Greek text renders correctly even on bare-bones containers that have no system fonts. On macOS and Windows only the JRE is bundled — those OSes already provide their own CoreText / GDI font subsystems with CJK coverage.

## Install

```bash
pip install pyplantuml-bundled
```

`pip` will pick the right wheel for your OS / arch / libc. Supported combinations (one wheel each):

| OS / libc | x86_64 | aarch64 / arm64 |
|---|---|---|
| Linux glibc (manylinux_2_28) | ✅ | ✅ |
| Linux musl (musllinux_1_2)   | ✅ | ✅ |
| macOS                        | ✅ | ✅ (Apple Silicon) |
| Windows                      | ✅ | — |

## Quick start

```bash
plantuml -tpng diagram.puml         # CLI mirrors the upstream plantuml.jar CLI
plantuml -checkonly diagram.puml    # static check only
```

```python
from pyplantuml import render, check, version, run

render("diagram.puml", fmt="svg", output_dir="out/")
assert check("diagram.puml")
print(version())                  # PlantUML version + JRE info

# Pass arbitrary plantuml.jar args:
proc = run(["-help"], capture_output=True)
```

Override the bundled JRE for debugging or to pin to a system JVM:

```bash
PYPLANTUML_JAVA=/path/to/java plantuml -tpng diagram.puml
```

## Why bundle the JRE?

PlantUML is widely used in CI, docs builds, lint hooks, and notebook sidecars. Telling every consumer to `apt install default-jre` is a pain when you only want a single Python entry point. This package trades wheel size (≈55–80 MB per platform) for a frictionless `pip install` story.

## How it works

```
pyplantuml/
├── __init__.py          – pure-Python launcher, sets up env + JVM flags
├── plantuml.jar         – bundled
├── jre/                 – jlink-stripped Temurin 17 (per-platform native bits)
└── runtime/
    ├── fonts.conf.template – materialised at first run with abs paths
    └── linux-<arch>/
        ├── lib/         – libfontconfig + freetype stack (Linux only)
        └── fonts/       – DejaVu + WenQuanYi MicroHei
```

The launcher invokes the bundled `java` with `-Djava.awt.headless=true`, sets `LD_LIBRARY_PATH` and `FONTCONFIG_FILE` on Linux so the JRE finds the embedded font subsystem, then `subprocess.run`s `plantuml.jar`.

## Building from source

```bash
make assets               # fetch jar, build JRE, stage Linux runtime libs
python -m build --wheel   # produce dist/*.whl for the current platform
pytest tests/             # render PNG / SVG / CJK byte-size sanity
```

For the multi-platform CI matrix see `.github/workflows/build.yml` — it uses `cibuildwheel` to produce one wheel per (OS, arch, libc).

## License

GPL-3.0-or-later, inherited from PlantUML upstream. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the full bundled-binary attribution.

## Versioning

The package version mirrors the bundled PlantUML release plus a build suffix, e.g. `1.2024.7.post1` means PlantUML 1.2024.7 + our 1st rebuild.
