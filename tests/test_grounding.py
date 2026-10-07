import pytest

from finance_ops.agent.grounding import answer_figures, unverified_figures

SOURCES = [
    '{"total":"1355.31","total_change":"-281.05","total_change_pct":94.5,'
    '"credits_recorded":4274720,"billed_minus_expected":"1637.36"}'
]


@pytest.mark.parametrize(
    "answer",
    [
        "The invoice was £1,355.31.",
        "The invoice was 1355.31 GBP.",
        "The invoice was GBP1,355.31.",
        "The invoice was about £1,355.",
        "It fell by £281.05.",  # sign does not matter
        "Up 94.5% on last month.",
        "About 4.27 million credits.",
        "Roughly 4.3m credits.",
        "Overbilled by about £1.6k.",
    ],
)
def test_figures_copied_or_rounded_from_tools_are_grounded(answer: str) -> None:
    assert unverified_figures(answer, SOURCES) == []


@pytest.mark.parametrize(
    ("answer", "flagged"),
    [
        ("The two invoices add up to £2,710.62.", ["£2,710.62"]),
        ("That is 12.6% of the year's billing.", ["12.6%"]),
        ("It rose by 281.06.", ["281.06"]),
    ],
)
def test_figures_the_model_worked_out_are_flagged(answer: str, flagged: list[str]) -> None:
    assert unverified_figures(answer, SOURCES) == flagged


def test_ids_dates_years_and_small_counts_are_not_treated_as_figures() -> None:
    answer = (
        "ACC-1007's invoice INV-202609-1007 for September 2026 (2026-09-01 to 2026-09-30) "
        "is missing 3 days, 21-23 Sept, see Q4 notes and CN-0001."
    )
    assert answer_figures(answer) == []


def test_small_counts_with_a_currency_symbol_are_still_checked() -> None:
    assert unverified_figures("A fee of £5 applies.", SOURCES) == ["£5"]


def test_figures_from_the_question_are_allowed() -> None:
    assert unverified_figures("Invoices more than 60 days overdue:", ["", "over 60 days?"]) == []


# --- from the pre-publication review -----------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "The fee is £2000.",
        "EUR 2050 a month",
        "overbilled by £1999.",
        "You owe 12 pounds.",
        "1,355.32GBP is due",
        "about £2k",
    ],
)
def test_amounts_with_currency_are_checked_even_when_they_look_like_years_or_counts(
    answer: str,
) -> None:
    assert unverified_figures(answer, ['{"total":"1281.05"}']) != []


def test_ids_and_dates_in_tool_output_do_not_ground_an_amount() -> None:
    source = '{"invoice_id":"INV-202609-1007","due_on":"2026-10-31","total":"2636.36"}'
    assert unverified_figures("overbilled by £1,007.00 or £202,609", [source]) == [
        "£1,007.00",
        "£202,609",
    ]


def test_a_comma_grouped_figure_after_a_month_is_not_a_date() -> None:
    assert unverified_figures("Over in September 65,969 credits", ['{"over":65969}']) == []


def test_a_comma_grouped_figure_from_the_question_is_allowed() -> None:
    assert unverified_figures("You asked about 65,969 credits.", ["about 65,969 credits?"]) == []
