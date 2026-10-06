PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin

.PHONY: help install lock test lint format sweep clean

help:  ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Create .venv with the pinned dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements/dev.txt
	$(BIN)/pip install --quiet --no-deps -e .

lock:  ## Regenerate requirements/*.txt from pyproject.toml
	$(BIN)/python scripts/lock.py

test:  ## Run the test suite (no API keys needed)
	$(BIN)/pytest

lint:  ## Lint and check formatting
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:  ## Apply formatting and safe lint fixes
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

sweep:  ## Pre-publish check for credentials and deny-listed terms
	scripts/sweep.sh

clean:  ## Remove caches and generated data
	rm -rf .pytest_cache .ruff_cache runs data/*.sqlite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
