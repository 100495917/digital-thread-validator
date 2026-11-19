PY ?= python
MBSE ?= mbse
BASE ?= origin/main
HEAD ?= HEAD

.PHONY: validate trace test test-selective reqcov security thread impact report gen site install clean all

validate:
	$(MBSE) validate all

trace:
	$(MBSE) trace check

test:
	$(PY) -m pytest

reqcov:
	$(MBSE) reqcov

security:
	$(MBSE) security

test-selective:
	@ids="$$($(PY) -m mbse.select_tests)"; \
	if [ -n "$$ids" ]; then $(PY) -m pytest $$ids; else echo "No tests selected"; fi

thread:
	$(MBSE) thread build

impact:
	$(MBSE) impact --base $(BASE) --head $(HEAD)

report:
	$(MBSE) report

gen:
	$(MBSE) generate all

site: gen
	mkdocs build --strict

install:
	$(PY) -m pip install -e '.[dev]'

clean:
	rm -rf build site htmlcov .pytest_cache .ruff_cache .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +

all: validate trace test thread impact report
