import sqlite3

from finance_ops.server.matching import match_accounts, words


def rows(*names: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE a (account_id TEXT, name TEXT)")
    conn.executemany(
        "INSERT INTO a VALUES (?, ?)", [(f"ACC-{1000 + i}", n) for i, n in enumerate(names)]
    )
    return conn.execute("SELECT * FROM a ORDER BY account_id").fetchall()


ACCOUNTS = rows(
    "Harbour Analytics Ltd", "Harbour Analytics Inc", "Kestrel Robotics Ltd", "Heron Media BV"
)


def ids(found: list[sqlite3.Row]) -> list[str]:
    return [r["account_id"] for r in found]


def test_legal_suffixes_are_ignored_when_comparing_words() -> None:
    assert words("Harbour Analytics Ltd.") == ["harbour", "analytics"]


def test_exact_full_name_beats_partial_matches() -> None:
    assert ids(match_accounts("Harbour Analytics Inc", ACCOUNTS)) == ["ACC-1001"]


def test_shared_name_without_suffix_matches_both() -> None:
    assert ids(match_accounts("harbour analytics", ACCOUNTS)) == ["ACC-1000", "ACC-1001"]


def test_prefix_and_small_typo_both_match() -> None:
    assert ids(match_accounts("Kest", ACCOUNTS)) == ["ACC-1002"]
    assert ids(match_accounts("Kestral Robotcs", ACCOUNTS)) == ["ACC-1002"]


def test_every_word_must_match() -> None:
    assert match_accounts("Kestrel Media", ACCOUNTS) == []


def test_a_query_of_only_a_legal_suffix_matches_nothing() -> None:
    assert match_accounts("Ltd", ACCOUNTS) == []


def test_all_matches_are_returned_for_the_tool_to_count() -> None:
    many = rows(*[f"Harbour Group {n}" for n in range(8)])
    assert len(match_accounts("Harbour Group", many)) == 8
