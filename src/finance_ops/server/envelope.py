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
import logging
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

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidInput(ToolProblem):
    status: Status = "invalid_input"


class NotFound(ToolProblem):
    status: Status = "not_found"


UNEXPECTED_FAILURE = "The tool failed unexpectedly. The details are in the server log."
logger = logging.getLogger(__name__)


def reports_problems(method: Callable[..., Envelope]) -> Callable[..., Envelope]:
    """Turn anything a tool method raises into an envelope.

    A ToolProblem becomes its own status. Any other exception becomes "error" with a
    generic message; the details go to the server log, never to the caller.
    """

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Envelope:
        try:
            return method(self, *args, **kwargs)
        except ToolProblem as problem:
            return envelope(problem.status, self.as_of, message=problem.message)
        except Exception:
            logger.exception("Tool %s failed", method.__name__)
            return envelope("error", self.as_of, message=UNEXPECTED_FAILURE)

    return wrapper
