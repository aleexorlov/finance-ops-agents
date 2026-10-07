"""Check that the figures in an answer came from a tool result.

The model is told never to calculate. This is the check that does not rely on
it listening: numbers are pulled out of the answer and each must match a number
in the tool results (or the question) at the precision the answer shows it.
"1,281.05", "£1,281" and "1.3k" all match a tool's "1281.05"; a figure the
model worked out for itself does not.

What is exempt, because it is not a figure:
- IDs (ACC-1007, INV-202609-1007), dates and times, in answers and in sources;
- years: whole numbers from 1900 to 2100 with no currency attached;
- small counts: whole numbers up to 12 with no currency attached ("3 days").
An amount with a currency symbol, code or word ("£2000", "1999 pounds") is
always checked. The small-count rule is a trade-off: a stray small count could
slip through, but the alternative is blocking ordinary sentences. The check is
lexical: it confirms a number appears in a source, not that it is used in the
right role.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
# A day number: one or two digits not followed by more digits, or by a thousands
# separator or decimal point and a digit (so "September 65,969" is not a date).
DAY = r"\d{1,2}(?![\d,.]\d|\d)"
NOT_FIGURES = re.compile(
    "|".join(
        [
            r"\b[A-Z]{2,4}-\d[\d-]*\b",  # IDs: ACC-1007, INV-202609-1007, CN-0001
            r"\d{4}-\d{2}(?:-\d{2})?(?:T[\d:.]+Z?)?",  # ISO dates, months and timestamps
            rf"\b{DAY}(?:st|nd|rd|th)?(?:\s*(?:-|\u2013|to|and)\s*{DAY}(?:st|nd|rd|th)?)?"
            rf"\s+{MONTHS}\b(?:\s+\d{{4}})?",  # 21 September 2026, 21-23 Sept
            rf"\b{MONTHS}\s+{DAY}(?:st|nd|rd|th)?(?:\s*(?:-|\u2013)\s*{DAY})?(?:,?\s+\d{{4}})?",
            rf"\b{MONTHS}\s+\d{{4}}\b",  # September 2026
            r"\b\d{1,2}:\d{2}(?::\d{2})?\b",  # times
        ]
    ),
    re.IGNORECASE,
)
FIGURE = re.compile(
    r"(?P<currency>[£$€]\s?)?(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<scale>%|percent\b|k\b|m\b|bn\b|million\b|thousand\b|billion\b))?",
    re.IGNORECASE,
)
CURRENCY_AFTER = re.compile(
    r"\s?(?:GBP|EUR|USD|pounds?|euros?|dollars?|pence|penny|cents?)\b", re.IGNORECASE
)
THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
SOURCE_NUMBER = re.compile(r"\d+(?:\.\d+)?")
SCALES = {
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "m": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}
SMALL_COUNT_LIMIT = 12
CURRENCY_CODES = frozenset({"GBP", "EUR", "USD"})


@dataclass(frozen=True)
class Figure:
    text: str
    value: Decimal
    places: int
    scale: Decimal


def _mask(text: str) -> str:
    return NOT_FIGURES.sub(lambda m: " " * len(m.group()), text)


def answer_figures(answer: str) -> list[Figure]:
    """Figures in an answer that need a source; IDs, dates, years and small counts excluded."""
    masked = _mask(answer)
    figures = []
    for match in FIGURE.finditer(masked):
        if _inside_word(masked, match.start(), match.end()):
            continue
        number = match.group("number").replace(",", "")
        scale_word = (match.group("scale") or "").lower()
        value = Decimal(number)
        places = len(number.split(".")[1]) if "." in number else 0
        is_whole = places == 0 and not scale_word
        has_currency = bool(match.group("currency")) or _currency_adjacent(masked, match)
        if is_whole and not has_currency and value <= SMALL_COUNT_LIMIT:
            continue
        plain_whole = is_whole and not has_currency and "," not in match.group("number")
        if plain_whole and 1900 <= value <= 2100:
            continue  # a year
        figures.append(
            Figure(match.group().strip(), value, places, SCALES.get(scale_word, Decimal(1)))
        )
    return figures


def source_numbers(sources: Iterable[str]) -> set[Decimal]:
    """Every number in the sources, as an absolute value.

    IDs, dates and times are masked first, as they are in answers, so an invented
    amount cannot borrow its digits from an invoice ID or a due date.
    """
    numbers = set()
    for text in sources:
        for token in SOURCE_NUMBER.findall(THOUSANDS.sub("", _mask(text))):
            try:
                numbers.add(abs(Decimal(token)))
            except InvalidOperation:
                continue
    return numbers


def is_grounded(figure: Figure, allowed: set[Decimal]) -> bool:
    if figure.scale != 1 and len(figure.value.normalize().as_tuple().digits) < 2:
        return False  # "£2k" would match anything from 1,500 to 2,499
    quantum = Decimal(1).scaleb(-figure.places)
    return any(
        (value / figure.scale).quantize(quantum, rounding=ROUND_HALF_UP) == figure.value
        for value in allowed
    )


def unverified_figures(answer: str, sources: Iterable[str]) -> list[str]:
    """Figures in `answer` that match no number in `sources`, in order of appearance."""
    allowed = source_numbers(sources)
    return [f.text for f in answer_figures(answer) if not is_grounded(f, allowed)]


def _currency_adjacent(text: str, match: re.Match[str]) -> bool:
    """A currency code just before the number, or a code or word just after it."""
    before = text[max(0, match.start() - 4) : match.start()].strip().upper()
    return before in CURRENCY_CODES or bool(CURRENCY_AFTER.match(text, match.end()))


def _inside_word(text: str, start: int, end: int) -> bool:
    """True for digits that are part of a word (Q4, 3x), but not GBP1,200 or 1,200GBP."""
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    after_currency_code = text[max(0, start - 3) : start].upper() in CURRENCY_CODES
    before_currency_code = text[end : end + 3].upper() in CURRENCY_CODES
    return (
        (before.isalpha() and not after_currency_code)
        or before == "_"
        or (after.isalpha() and not before_currency_code)
    )
