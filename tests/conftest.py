from pathlib import Path

import pytest

from finance_ops.data.generate import write_database


@pytest.fixture(scope="session")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One generated database shared by the whole test session (default seed)."""
    path = tmp_path_factory.mktemp("data") / "finance_ops.sqlite"
    write_database(path)
    return path
