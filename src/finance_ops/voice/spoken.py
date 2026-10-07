"""Turn spoken numbers back into digits, so a voice transcript can be figure-checked.

The voice agent is told to say amounts the way a person would: "one thousand and
forty-two pounds ninety-six". The figure check works on digits, so this rewrites
such phrases as "1042.96 pounds" first. It handles whole numbers up to the
millions, "<n> pounds|euros|dollars <m>" as a decimal amount, "<m> pence|cents",
and "point" decimals ("nought point eight" -> "0.8").
"""

import re

UNITS = {
    "zero": 0, "nought": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}  # fmt: skip
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}
CURRENCIES = ("pounds", "pound", "euros", "euro", "dollars", "dollar")
MINOR_UNITS = ("pence", "penny", "cents", "cent")
NUMBER_WORD = "|".join([*UNITS, *TENS, *SCALES])
# A run of number words, allowing "and" and hyphens between them ("forty-two").
RUN = re.compile(
    rf"\b(?:{NUMBER_WORD})(?:(?:\s+and\s+|\s+|-)(?:{NUMBER_WORD}))*\b(?:\s+point(?:\s+(?:{NUMBER_WORD}))+)?",
    re.IGNORECASE,
)
AMOUNT = re.compile(
    rf"\b(\d+)\s+({'|'.join(CURRENCIES)})(?:\s+and)?\s+(\d{{1,2}})\b(?!\.\d)", re.IGNORECASE
)
MINOR = re.compile(rf"\b(\d{{1,2}})\s+({'|'.join(MINOR_UNITS)})\b", re.IGNORECASE)


def words_to_number(phrase: str) -> str:
    """'one thousand and forty-two' -> '1042'; 'nought point eight' -> '0.8'."""
    whole, _, decimals = phrase.lower().partition(" point ")
    words = [w for w in re.split(r"[\s-]+", whole) if w and w != "and"]
    if "oh" in words:  # an ID read digit by digit: "ten oh seven" is 1007, not 17
        return "".join(str(UNITS.get(w, TENS.get(w, ""))) for w in words)
    total, current = 0, 0
    for word in words:
        if word in UNITS:
            current += UNITS[word]
        elif word in TENS:
            current += TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word in SCALES:
            total += max(current, 1) * SCALES[word]
            current = 0
    number = str(total + current)
    if decimals:
        number += "." + "".join(str(UNITS.get(w, "")) for w in decimals.split())
    return number


def to_digits(text: str) -> str:
    """Rewrite spoken numbers and amounts in `text` as digits."""
    text = RUN.sub(lambda m: words_to_number(m.group()), text)
    text = AMOUNT.sub(lambda m: f"{m.group(1)}.{int(m.group(3)):02d} {m.group(2)}", text)
    return MINOR.sub(lambda m: f"0.{int(m.group(1)):02d}", text)
