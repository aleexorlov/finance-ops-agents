"""Match a typed or spoken company name to account records.

An exact full-name match wins outright. Otherwise every word of the query must
match a word of the name, either as a prefix ("Kest" -> "Kestrel") or closely
enough to survive a typo or a speech-to-text slip ("Kestral" -> "Kestrel").
Legal suffixes are ignored, which is why "Harbour Analytics" matches both the
Ltd and the Inc: that ambiguity is real and is reported, not resolved here.
"""

import re
import sqlite3
from difflib import SequenceMatcher

LEGAL_SUFFIXES = frozenset({"ltd", "limited", "inc", "gmbh", "sas", "bv", "llc", "plc"})
WORD_SIMILARITY_THRESHOLD = 0.8
MAX_MATCHES = 5  # how many matches a tool shows; it reports the total too


def words(name: str) -> list[str]:
    tokens = re.sub(r"[^0-9a-z]+", " ", name.casefold()).split()
    return [t for t in tokens if t not in LEGAL_SUFFIXES]


def word_score(query_word: str, name_words: list[str]) -> float:
    best = 0.0
    for word in name_words:
        if word.startswith(query_word):
            return 1.0
        best = max(best, SequenceMatcher(None, query_word, word).ratio())
    return best


def match_accounts(query: str, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    exact = [r for r in rows if r["name"].casefold() == query.casefold()]
    if exact:
        return exact
    query_words = words(query)
    if not query_words:
        return []
    scored = []
    for row in rows:
        scores = [word_score(w, words(row["name"])) for w in query_words]
        if min(scores) >= WORD_SIMILARITY_THRESHOLD:
            scored.append((sum(scores) / len(scores), row["account_id"], row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored]
