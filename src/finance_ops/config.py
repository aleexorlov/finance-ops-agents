"""Paths and settings shared by the data generator, the server and the agent."""

import os
from pathlib import Path

DEFAULT_DB_PATH = Path("data/finance_ops.sqlite")


def db_path() -> Path:
    """Database location: FINANCE_OPS_DB if set, otherwise data/finance_ops.sqlite."""
    return Path(os.environ.get("FINANCE_OPS_DB", DEFAULT_DB_PATH))
