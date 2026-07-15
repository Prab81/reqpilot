"""Reviewable prompt contract for Phase-Delivery story generation."""
from __future__ import annotations

import json
from typing import Any

from src.intelligence.state import Utterance, mmss


STORY_SCHEMA_HINT = """{
  "title": "delivery package title",
  "epics": [{
    "id": "E1", "title": "short outcome-oriented title",
    "description": "business outcome and scope",
    "requirement_ids": ["R1"], "evidence_utterances": [1]
  }],
  "stories": [{
    "id": "US1", "epic_id": "E1", "title": "short deliverable title",
    "as_a": "specific actor", "i_want": "capability", "so_that": "business value",
    "acceptance_criteria": [{"given": "precondition", "when": "action", "then": "observable result"}],
    "requirement_ids": ["R1"], "evidence_utterances": [1]
  }]
}"""


def build_story_prompt(
    state: dict[str, Any], utterances: list[Utterance], previous: dict[str, Any] | None = None
) -> tuple[str, str]:
    system = """You are a senior business analyst decomposing approved workshop findings into Jira-ready work.
Generate a small set of cohesive epics and independently testable user stories. Every story must use the supplied
As a / I want / So that fields and contain concrete Given/When/Then acceptance criteria. Do not invent policy,
numbers, systems, actors, or decisions. Use only requirement IDs and utterance IDs present in the input. Preserve
the IDs of semantically unchanged epics, stories, and acceptance criteria from the previous package. Keep conflicts
and unresolved questions out of acceptance criteria; phrase them as assumptions only when explicitly resolved."""
    transcript = [
        {"id": u.id, "timestamp": mmss(u.t0), "text": u.text}
        for u in utterances
    ]
    payload = {
        "session_state": state,
        "transcript_evidence": transcript,
        "previous_delivery_package": previous or {},
    }
    return system, "Create the delivery package from this source JSON:\n" + json.dumps(payload, ensure_ascii=False)

