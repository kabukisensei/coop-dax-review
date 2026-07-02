# Dev entry points for coop-dax-review. Run from the repo root.
#
# Every target uses `.venv/bin/python -m <module>` — NEVER the venv console
# scripts (.venv/bin/pytest etc.): those hard-code the venv's creation path in
# their shebang and break with "bad interpreter" if the repo moves on disk.

VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: setup test lint build release-check

setup:  ## one-time: create the venv and install dev deps
	python3 -m venv $(VENV)
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m pytest -q

test:
	$(PY) -m pytest -q

lint:   ## the exact two commands CI's lint job gates on
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

build:  ## sdist + wheel into a clean dist/ (removes stale artifacts first)
	rm -rf dist
	$(PY) -m pip show -q build 2>/dev/null || $(PY) -m pip install -q build
	$(PY) -m build

release-check:  ## version single-source + standards sync (same checks as .githooks/pre-commit)
	sh scripts/release-check.sh
