from __future__ import annotations

import pytest

from src.intelligence.state import (
    Utterance,
    empty_state,
    stabilize_state_ids,
    validate_state,
    valid_mermaid,
)
from tests.fixtures.meeting_transcript import pass1_state


def test_fixture_state_validates_without_loss() -> None:
    source = pass1_state()
    clean, problems = validate_state(source)
    assert problems == []
    assert clean == source


def test_validation_drops_unsafe_items_and_sanitizes_evidence() -> None:
    source = empty_state()
    source.update({
        "summary": [" useful ", 42, ""],
        "requirements": [
            {"id": "R1", "text": "Keep me", "status": "captured",
             "evidence_utterances": [2, 2, -1, True, "3"]},
            {"id": "R1", "text": "Duplicate", "status": "captured"},
            {"id": "bad", "text": "Bad ID", "status": "captured"},
        ],
        "open_questions": [
        {"id": "Q1", "text": "Linked?", "status": "suggested",
             "category": "data", "requirement_id": "R99"},
        ],
        "metrics": [
            {"id": "M1", "title": "Broken", "kind": "bar",
             "labels": ["a"], "values": [1, 2]},
        ],
        "diagrams": [
            {"id": "G1", "title": "Unsafe", "kind": "flowchart",
             "mermaid": "flowchart TD\nA[\"A\"] --> B[\"B\"]\nclick A evil"},
        ],
    })

    clean, problems = validate_state(source)

    assert clean["summary"] == ["useful"]
    assert clean["requirements"][0]["evidence_utterances"] == [2]
    assert len(clean["requirements"]) == 1
    assert "requirement_id" not in clean["open_questions"][0]
    assert clean["metrics"] == []
    assert clean["diagrams"] == []
    assert any("duplicate id" in problem for problem in problems)
    assert any("unsafe Mermaid" in problem for problem in problems)


@pytest.mark.parametrize("source", [
    "graph TD\nA --> B",
    "flowchart TD; A --> B",
    "flowchart TD\nsubgraph bad\nA --> B\nend",
    "flowchart TD\nA[unquoted] --> B[\"ok\"]",
])
def test_mermaid_contract_rejects_non_strict_source(source: str) -> None:
    assert not valid_mermaid(source)


def test_stable_ids_are_repaired_and_question_link_follows() -> None:
    previous = empty_state()
    previous["requirements"] = [
        {"id": "R1", "text": "Applications are retained for seven years.",
         "status": "captured", "evidence_utterances": [7]},
    ]
    state = empty_state()
    state["requirements"] = [
        {"id": "R9", "text": "Applications are retained for seven years.",
         "status": "confirmed", "evidence_utterances": [7, 9]},
        {"id": "R12", "text": "Applications are then purged.",
         "status": "captured", "evidence_utterances": [9]},
    ]
    state["open_questions"] = [
        {"id": "Q8", "text": "Who owns the purge?", "status": "suggested",
         "category": "actors", "requirement_id": "R9"},
    ]

    repairs = stabilize_state_ids(state, previous)

    assert [item["id"] for item in state["requirements"]] == ["R1", "R2"]
    assert state["open_questions"][0]["id"] == "Q1"
    assert state["open_questions"][0]["requirement_id"] == "R1"
    assert repairs == ["requirements: repaired R9 to stable R1"]


def test_utterance_rejects_invalid_timing() -> None:
    with pytest.raises(ValueError):
        Utterance(id=1, t0=2.0, t1=1.0, text="backwards")
    with pytest.raises(ValueError):
        Utterance(id=True, t0=0.0, t1=1.0, text="bool id")
