"""Read-only access to the synthetic database.

The connection is opened with SQLite's read-only mode and query_only set, so a
bug in a tool cannot write even if one tried. No module in this package issues
INSERT, UPDATE or DELETE against this connection.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Snapshot:
    """The moment the data represents. Tools treat snapshot_date as 'today'."""

    snapshot_date: date
    snapshot_time: str
    reporting_currency: str
    notice: str


class Database:
    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"No database at {path}. Generate it with: make data")
        self._uri = f"{path.resolve().as_uri()}?mode=ro"
        self.snapshot = self._load_snapshot()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            yield conn
        finally:
            conn.close()

    def _load_snapshot(self) -> Snapshot:
        with self.connect() as conn:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        return Snapshot(
            snapshot_date=date.fromisoformat(meta["snapshot_date"]),
            snapshot_time=meta["snapshot_time"],
            reporting_currency=meta["reporting_currency"],
            notice=meta["notice"],
        )
