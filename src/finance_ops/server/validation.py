"""Argument checks. Each returns the normalised value or raises InvalidInput."""

import calendar
import re
from datetime import date

from finance_ops.server.envelope import InvalidInput

ACCOUNT_ID = re.compile(r"ACC-\d{4}")
INVOICE_ID = re.compile(r"INV-\d{6}-\d{4}")
MONTH = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
MAX_DAYS_OVERDUE = 3650


def account_id(raw: str) -> str:
    value = str(raw).strip().upper()
    if not ACCOUNT_ID.fullmatch(value):
        raise InvalidInput(
            f"account_id must look like ACC-1234, for example ACC-1007; got {raw!r}. "
            "If you only have a name, call find_accounts first."
        )
    return value


def invoice_id(raw: str) -> str:
    value = str(raw).strip().upper()
    if not INVOICE_ID.fullmatch(value):
        raise InvalidInput(
            f"invoice_id must look like INV-YYYYMM-NNNN, for example INV-202609-1007; got "
            f"{raw!r}. Use list_invoices to find an account's invoice IDs."
        )
    return value


def month(raw: str) -> tuple[date, date]:
    """'2026-09' -> (first day, last day) of that month."""
    match = MONTH.fullmatch(str(raw).strip())
    if not match:
        raise InvalidInput(f"month must be YYYY-MM, for example 2026-09; got {raw!r}.")
    year, number = int(match.group(1)), int(match.group(2))
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])


def name_query(raw: str) -> str:
    value = " ".join(str(raw).split())
    if not 2 <= len(value) <= 80:
        raise InvalidInput("name_query must be 2 to 80 characters, for example 'Kestrel'.")
    return value


def min_days_overdue(raw: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= MAX_DAYS_OVERDUE:
        raise InvalidInput(
            f"min_days_overdue must be a whole number from 1 to {MAX_DAYS_OVERDUE}, "
            f"for example 60; got {raw!r}."
        )
    return raw
