.PHONY: assets jar jre runtime wheel test clean distclean

assets: jar jre runtime

jar:
	bash scripts/fetch_plantuml_jar.sh

jre:
	bash scripts/build_jre.sh

runtime:
	@case "$$(uname -s)" in \
	  Linux) bash scripts/stage_linux_runtime.sh ;; \
	  Darwin|MINGW*|MSYS*|CYGWIN*) echo "skip Linux runtime staging on $$(uname -s)" ;; \
	  *) echo "unknown OS"; exit 1 ;; \
	esac

wheel:
	python -m build --wheel

test:
	python -m pytest -v tests/

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

distclean: clean
	rm -rf src/pyplantuml/plantuml.jar src/pyplantuml/jre src/pyplantuml/runtime/linux-*
