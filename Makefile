PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
# Put src/ on the path directly rather than relying on the editable install's
# .pth file: on an iCloud-synced folder macOS flags files in .venv as hidden,
# and Python skips hidden .pth files.
export PYTHONPATH := $(CURDIR)/src

.PHONY: help install lock data serve serve-http ask test lint format sweep clean

help:  ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Create .venv with the pinned dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements/dev.txt
	$(BIN)/pip install --quiet --no-deps -e .

lock:  ## Regenerate requirements/*.txt from pyproject.toml
	$(BIN)/python scripts/lock.py

data:  ## Generate the synthetic database (data/finance_ops.sqlite)
	$(BIN)/python -m finance_ops.data.generate

serve:  ## Run the MCP server over stdio (Agent A starts this itself)
	$(BIN)/python -m finance_ops.server

serve-http:  ## Run the MCP server over HTTP on :8080 (needs MCP_AUTH_TOKEN in the environment)
	$(BIN)/python -m finance_ops.server --transport http --port 8080

ask:  ## Ask Agent A a question: make ask Q="Why did Kestrel Robotics' September invoice go up?"
	$(BIN)/python -m finance_ops.agent --trace "$(Q)"

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
