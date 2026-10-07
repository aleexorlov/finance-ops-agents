"""Check a finished voice call: every figure the agent said, against the tools' results.

Agent A can withhold an answer whose figures no tool returned. A voice agent
cannot: it has already spoken. This is the voice equivalent, run after the call.
It takes the call's transcript from ElevenLabs, turns spoken numbers back into
digits, and applies Agent A's figure check to each agent turn, using the tool
results recorded in the same call (and the caller's own words) as the sources.

    python -m finance_ops.voice.audit                     # latest call to the agent
    python -m finance_ops.voice.audit --conversation-id conv_...
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from finance_ops.agent.grounding import answer_figures, unverified_figures
from finance_ops.voice.elevenlabs import ElevenLabsClient, Request
from finance_ops.voice.spoken import to_digits

REPO = Path(__file__).resolve().parents[3]
EXPRESSIVE_TAG = re.compile(r"\[[a-z ]+\]\s*", re.IGNORECASE)  # e.g. "[concerned]"


@dataclass(frozen=True)
class TurnCheck:
    time_secs: int | None
    interrupted: bool
    said: str
    heard_as: str
    figures: tuple[str, ...]
    unverified: tuple[str, ...]


@dataclass(frozen=True)
class CallAudit:
    turns: tuple[TurnCheck, ...]
    tool_calls: tuple[str, ...]

    @property
    def figures_checked(self) -> int:
        return sum(len(t.figures) for t in self.turns)

    @property
    def unverified(self) -> tuple[str, ...]:
        return tuple(f for t in self.turns for f in t.unverified)


def audit_transcript(transcript: list[dict[str, Any]]) -> CallAudit:
    """Figure-check every agent turn against the call's tool results and caller turns."""
    sources = [
        result.get("result_value") or ""
        for turn in transcript
        for result in (turn.get("tool_results") or [])
    ]
    sources += [turn.get("message") or "" for turn in transcript if turn.get("role") == "user"]
    sources = [to_digits(s) for s in sources]
    tool_calls = tuple(
        call.get("tool_name", "?").split("_", 1)[-1]
        for turn in transcript
        for call in (turn.get("tool_calls") or [])
    )
    checks = []
    for turn in transcript:
        # original_message is the full text the model generated. When the caller cuts
        # the agent off, message stops mid-word ("six hundred and t..."), which would
        # read as a wrong figure; the generated text holds every figure the model chose.
        generated = turn.get("original_message") or turn.get("message") or ""
        said = EXPRESSIVE_TAG.sub("", generated).strip()
        if turn.get("role") != "agent" or not said:
            continue
        heard = to_digits(said)
        checks.append(
            TurnCheck(
                time_secs=turn.get("time_in_call_secs"),
                interrupted=bool(turn.get("interrupted")),
                said=said,
                heard_as=heard,
                figures=tuple(f.text for f in answer_figures(heard)),
                unverified=tuple(unverified_figures(heard, sources)),
            )
        )
    return CallAudit(tuple(checks), tool_calls)


def fetch_transcript(
    client: ElevenLabsClient, agent_id: str, conversation_id: str | None
) -> tuple[str, list[dict[str, Any]]]:
    if conversation_id is None:
        listing = client.send(
            Request("GET", f"/v1/convai/conversations?agent_id={agent_id}&page_size=1", {})
        )
        conversations = listing.get("conversations") or []
        if not conversations:
            sys.exit("No conversations found for this agent yet.")
        conversation_id = conversations[0]["conversation_id"]
    detail = client.send(Request("GET", f"/v1/convai/conversations/{conversation_id}", {}))
    return conversation_id, detail.get("transcript") or []


def main() -> None:
    parser = argparse.ArgumentParser(description="Figure-check a finished voice call.")
    parser.add_argument("--conversation-id", help="default: the agent's latest call")
    args = parser.parse_args()
    load_dotenv(REPO / ".env")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    agent_id = os.environ.get("ELEVENLABS_AGENT_ID", "")
    if not (api_key and agent_id):
        sys.exit("Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in .env.")
    conversation_id, transcript = fetch_transcript(
        ElevenLabsClient(api_key), agent_id, args.conversation_id
    )
    audit = audit_transcript(transcript)
    print(
        f"Call {conversation_id}: {len(audit.turns)} agent turns, tools used: "
        f"{', '.join(audit.tool_calls) or 'none'}"
    )
    for turn in audit.turns:
        mark = "UNVERIFIED " + ", ".join(turn.unverified) if turn.unverified else "ok"
        cut = " (transcript cut short)" if turn.interrupted else ""
        print(f"  [{turn.time_secs}s] {mark}{cut}: {turn.said[:100]}")
    print(
        f"{audit.figures_checked} figures checked, {len(audit.unverified)} not found "
        "in the call's tool results."
    )
    sys.exit(1 if audit.unverified else 0)


if __name__ == "__main__":
    main()
