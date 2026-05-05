# Contributing

Thanks for considering a contribution. The single source of truth for "how this codebase is meant to evolve" is [`AGENTS.md`](AGENTS.md) — read it before starting any non-trivial change. The same file is mounted as `CLAUDE.md` (symlink) so AI coding assistants see the same rules.

## Quick start

```bash
git clone https://github.com/HansBug/pyplantuml-bundled
cd pyplantuml-bundled

# JDK 17 with jmods/ is required (Eclipse Temurin 17 works).
export JAVA_HOME=/path/to/jdk17

make assets               # fetch jar, jlink JRE, stage Linux native libs
python -m build --wheel   # produces dist/pyplantuml_bundled-*.whl
pip install pytest dist/*.whl
pytest tests/             # 12 tests
```

If you only need to iterate on Python source you can `pip install -e .` after `make assets`.

## What to keep in mind

- **Do not commit binaries.** `plantuml.jar`, `jre/`, and `runtime/linux-*/` are produced by `scripts/` and are gitignored. The exception is `vendored/fonts/` (~6 MB total) which is committed because the fonts are tiny, stable, and architecture-independent.
- **Do not break the wheel tag.** The wheel must stay `py3-none-{platform}` so one wheel works on Python 3.7 – 3.14. The override lives in `setup.py`. Do not introduce a `cp310-cp310-…` style ABI tag unless you have a very good reason.
- **Do not stage Linux runtime libraries from anywhere other than the manylinux / musllinux container that produces the wheel.** Mixing glibc baselines is the most common way to ship a wheel that crashes at import time on older distros.
- **CJK rendering must stay visually correct.** Tofu glyphs do not raise errors, so byte-size + minimum width assertions in `tests/test_cjk.py` are how we catch regressions. If you change the font setup, run `pytest tests/test_cjk.py -v` and inspect a rendered PNG manually.

## Reporting issues

When opening an issue please include:

1. The wheel filename you installed (`pip show pyplantuml-bundled` plus `pip debug --verbose | grep -E "Compatible tags"`).
2. The OS / arch / libc.
3. Output of `plantuml -version` (so we know which JRE is in play).
4. A minimal `.puml` source that reproduces the problem.

For "PlantUML doesn't render my diagram correctly" issues: please first try the same `.puml` against [the official PlantUML web demo](https://www.plantuml.com/plantuml/) to rule out an upstream issue.

## License

By contributing you agree your work is licensed under GPL-3.0-or-later, matching the project license.
