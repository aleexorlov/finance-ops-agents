"""Paths and settings shared by the data generator, the server and the agent."""

import os
from pathlib import Path

# Anchored to the repository, so the server finds the data from any working directory.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "finance_ops.sqlite"


def db_path() -> Path:
    """Database location: FINANCE_OPS_DB if set and non-empty, else data/finance_ops.sqlite."""
    return Path(os.environ.get("FINANCE_OPS_DB") or DEFAULT_DB_PATH)
