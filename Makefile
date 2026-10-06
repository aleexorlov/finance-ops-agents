PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
# Put src/ on the path directly rather than relying on the editable install's
# .pth file: on an iCloud-synced folder macOS flags files in .venv as hidden,
# and Python skips hidden .pth files.
export PYTHONPATH := $(CURDIR)/src

.PHONY: help install lock data serve serve-http smoke docker-build docker-run ask eval eval-estimate test lint format sweep clean

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

smoke:  ## Smoke-test a running HTTP server: make smoke URL=http://localhost:8080 (uses MCP_AUTH_TOKEN)
	scripts/smoke_test.sh "$(or $(URL),http://localhost:8080)" "$$MCP_AUTH_TOKEN"

docker-build:  ## Build the server image
	docker build -t finance-ops-mcp .

docker-run:  ## Run the server image on :8080 (needs MCP_AUTH_TOKEN in the environment)
	docker run --rm -p 8080:8080 -e MCP_AUTH_TOKEN finance-ops-mcp

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

eval-estimate:  ## Estimate the cost of a full evaluation run (no API calls)
	$(BIN)/python -m finance_ops.evals --estimate

eval:  ## Run the known-answer evaluation (needs ANTHROPIC_API_KEY; see make eval-estimate)
	$(BIN)/python -m finance_ops.evals --repeats 5
