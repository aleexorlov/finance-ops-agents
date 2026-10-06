"""The response shape every tool returns, and the problems tools can report.

status is always one of:
  ok             the data answers the request
  partial        data returned, but part of it is missing (for example days of usage)
  stale          data returned, but a feed has not caught up with the snapshot date
  not_found      the ID or name does not exist
  ambiguous      a name matched more than one account; ask the user which one
  invalid_input  an argument is malformed; the message gives the expected format
  error          the tool failed; no data
"""

import functools
from collections.abc import Callable, Iterable
from typing import Any, Literal

Status = Literal["ok", "partial", "stale", "not_found", "ambiguous", "invalid_input", "error"]
Envelope = dict[str, Any]


def envelope(
    status: Status,
    as_of: str,
    data: dict[str, Any] | None = None,
    message: str | None = None,
    warnings: Iterable[str] = (),
) -> Envelope:
    return {
        "status": status,
        "message": message,
        "as_of": as_of,
        "warnings": list(warnings),
        "data": data,
    }


class ToolProblem(Exception):
    """Raised inside a tool to return a non-ok envelope instead of data."""

    status: Status = "error"

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data


class InvalidInput(ToolProblem):
    status: Status = "invalid_input"


class NotFound(ToolProblem):
    status: Status = "not_found"


def reports_problems(method: Callable[..., Envelope]) -> Callable[..., Envelope]:
    """Turn a ToolProblem raised by a tool method into an envelope with that status."""

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Envelope:
        try:
            return method(self, *args, **kwargs)
        except ToolProblem as problem:
            return envelope(problem.status, self.as_of, data=problem.data, message=problem.message)

    return wrapper
