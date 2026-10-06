"""Run log: one JSON line per event, one file per run, under runs/.

Records the question, every model turn, every tool call with its arguments and
status, and the final outcome, so any answer can be traced back to the data.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class RunLog(Protocol):
    def event(self, kind: str, **fields: Any) -> None: ...


class JsonlRunLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def event(self, kind: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "event": kind}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**record, **fields}, default=str) + "\n")


class NullRunLog:
    def event(self, kind: str, **fields: Any) -> None:
        return None
