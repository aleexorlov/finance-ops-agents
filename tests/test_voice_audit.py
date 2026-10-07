"""The voice agent's after-the-call figure check, and the spoken-number converter it needs."""

import json

import pytest

from finance_ops.voice.audit import audit_transcript
from finance_ops.voice.spoken import to_digits


@pytest.mark.parametrize(
    ("spoken", "digits"),
    [
        ("owes one thousand and forty-two pounds ninety-six", "owes 1042.96 pounds"),
        ("rose by one thousand two hundred and eighty-one pounds five", "rose by 1281.05 pounds"),
        (
            "overbilled by one thousand six hundred and thirty-seven pounds thirty-six.",
            "overbilled by 1637.36 pounds.",
        ),  # sentence-final: found by the first real call
        ("a total of nine hundred and ninety-nine pounds", "a total of 999 pounds"),
        ("twenty-nine euros ninety", "29.90 euros"),
        ("about forty-nine pence", "about 0.49"),
        ("nought point eight pounds per thousand", "0.8 pounds per 1000"),
        (
            "four million two hundred and seventy-four thousand seven hundred and twenty credits",
            "4274720 credits",
        ),
        ("invoice ending ten oh seven", "invoice ending 1007"),  # an ID read digit by digit
    ],
)
def test_spoken_numbers_become_digits(spoken: str, digits: str) -> None:
    assert to_digits(spoken) == digits


def tool_result(name: str, payload: dict) -> dict:
    return {"tool_name": f"finance-ops_{name}", "result_value": json.dumps(payload)}


TRANSCRIPT = [
    {"role": "agent", "message": "Hi, the data is synthetic. What would you like to know?"},
    {"role": "user", "message": "Was invoice INV-202609-1007 billed correctly?"},
    {
        "role": "agent",
        "message": "",
        "tool_calls": [{"tool_name": "finance-ops_reconcile_invoice"}],
    },
    {
        "role": "agent",
        "message": "",
        "tool_results": [
            tool_result(
                "reconcile_invoice",
                {"billed_minus_expected": "1637.36", "expected": {"total": "999.00"}},
            ),
        ],
    },
    {
        # Cut short in the transcript; the full generated text is in original_message.
        "role": "agent",
        "interrupted": True,
        "message": "[concerned] No. It was overbilled by one thousand six hundred and t...",
        "original_message": "[concerned] No. It was overbilled by one thousand six hundred "
        "and thirty-seven pounds thirty-six. It should be nine hundred and ninety-nine pounds.",
    },
    {"role": "user", "message": "And the one before?"},
    {"role": "agent", "message": "That one was overbilled by two hundred pounds."},
]


def test_audit_checks_every_spoken_figure_against_the_calls_tool_results() -> None:
    audit = audit_transcript(TRANSCRIPT)
    assert audit.tool_calls == ("reconcile_invoice",)
    assert audit.figures_checked == 3
    assert audit.unverified == ("200",)  # said, but no tool in the call returned it


def test_audit_uses_the_generated_text_when_the_transcript_is_cut_short() -> None:
    interrupted = audit_transcript(TRANSCRIPT).turns[1]
    assert interrupted.interrupted is True
    assert interrupted.unverified == ()  # "six hundred and t..." is not read as 600
    assert "[concerned]" not in interrupted.said
