# Backend dev shortcuts — run from apps/backend/
# Linux / macOS / WSL / Git-Bash. Native Windows PowerShell, use DEV_SETUP.md.

PYTHON ?= python3.11
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PYTEST := PYTHONPATH=src $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff

.PHONY: help install install-with-sdk test test-rfq test-escrow test-watcher \
        lint lint-fix ci clean

help:
	@echo "Backend dev targets:"
	@echo ""
	@echo "  make install          create venv + install backend dev deps"
	@echo "  make install-with-sdk install + the Python SDK (CI parity)"
	@echo ""
	@echo "  make test             full pytest suite"
	@echo "  make test-rfq         tests/test_rfq.py only"
	@echo "  make test-escrow      tests/test_escrow_dispatch.py only"
	@echo "  make test-watcher     tests/test_chain_watcher_filter.py only"
	@echo ""
	@echo "  make lint             ruff check ."
	@echo "  make lint-fix         ruff check --fix ."
	@echo "  make ci               exactly what CI runs (ruff + pytest)"
	@echo ""
	@echo "  make clean            remove .venv + caches"

$(VENV)/bin/pytest:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

install: $(VENV)/bin/pytest

install-with-sdk: install
	$(PIP) install -e ../../packages/sdk-python

test: install
	$(PYTEST)

test-rfq: install
	$(PYTEST) tests/test_rfq.py -v

test-escrow: install
	$(PYTEST) tests/test_escrow_dispatch.py -v

test-watcher: install
	$(PYTEST) tests/test_chain_watcher_filter.py -v

lint: install
	$(RUFF) check .

lint-fix: install
	$(RUFF) check --fix .

ci: install-with-sdk
	$(RUFF) check .
	$(PYTEST) -v

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
