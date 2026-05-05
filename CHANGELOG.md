# Changelog

All notable changes to this project will be documented here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows the convention `<plantuml-version>.<wrapper-revision>` for version numbers — first three segments mirror the bundled `plantuml.jar`, the trailing segment is incremented on wrapper-only fixes.

## [1.2024.7.1] — 2026-05-06

Initial public release.

### Added
- Pre-built wheels for 8 `(OS, arch, libc)` targets, one wheel per platform, all `py3-none-{platform}` so a single wheel covers Python 3.7 – 3.14:
  - `manylinux_2_28_x86_64`, `manylinux_2_28_aarch64`
  - `musllinux_1_2_x86_64`, `musllinux_1_2_aarch64`
  - `macosx_11_0_x86_64`, `macosx_11_0_arm64`
  - `win_amd64`, `win_arm64`
- Bundled `jlink`-stripped Eclipse Temurin 17 JRE (Microsoft OpenJDK 17 on Windows ARM64 — Adoptium has no `win-aarch64` Temurin 17 build).
- Bundled `plantuml.jar` 1.2024.7.
- On Linux, bundled `libfontconfig` chain plus DejaVu Sans + WenQuanYi Micro Hei so CJK / Cyrillic / Greek render in scratch / slim containers without any system fonts.
- Python API: `render`, `check`, `version`, `run`, `JAR_PATH`, `JAVA_BIN`, `PlantUmlError`.
- `plantuml` console script that proxies arguments to the bundled `plantuml.jar`.
- `PYPLANTUML_JAVA` env var to override the bundled JRE.
- `cibuildwheel`-based GitHub Actions matrix, runner choices favour the lowest currently-available free runner per platform (`ubuntu-22.04(-arm)`, `macos-14`, `macos-15-intel`, `windows-2022`, `windows-11-arm`) for maximum end-user OS compatibility.

### Verified
- 12 / 12 pytest cases pass on every produced wheel via `cibuildwheel`'s test step.
- Same Linux x86_64 wheel passes 12 / 12 pytest on Python 3.7.17, 3.8.20, 3.9.25, 3.10.20, 3.11.15, 3.12.13, 3.13.13, 3.14.4 — confirms one `py3-none-{plat}` wheel really covers the full version range.
- CJK rendering visually verified (sequence, class, state, component diagrams render PNG / SVG with no tofu glyphs).

### Known limitations
- `auditwheel` / `delocate` are explicitly disabled — we manage native libs manually via `LD_LIBRARY_PATH` and would otherwise fight repair tooling.
- GraphViz (`dot`) is **not** bundled. Install it from your system package manager if you need component / class diagram auto-layout. Bundling it would roughly double wheel size.
- Fontconfig may emit a benign `unknown element "reset-dirs"` warning on Linux when the system config differs from the bundled `libfontconfig`'s expected schema. Rendering is unaffected.
