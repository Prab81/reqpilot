from __future__ import annotations

import copy

import pytest

from src.delivery import DeliveryRepository, DeliveryValidationError, StoryService
from src.intelligence.providers import MockProvider
from src.sessions.store import SessionStore
from tests.fixtures.meeting_transcript import pass2_state, utterances


def _session(tmp_path) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session()
    for utterance in utterances():
        store.append_utterance(session_id, utterance)
    store.snapshot_state(session_id, pass2_state(), 2, analyzed_through=30)
    return store, session_id


def _response() -> dict:
    return {
        "title": "Consumer lending delivery backlog",
        "epics": [
            {"id": "E8", "title": "Digital application intake",
             "description": "Capture applications once and route them consistently.",
             "requirement_ids": ["R1", "R7"], "evidence_utterances": [5, 14, 999]},
            {"id": "E9", "title": "Underwriting workflow",
             "description": "Give underwriting a controlled and observable workflow.",
             "requirement_ids": ["R3", "R4", "R10"], "evidence_utterances": [8, 10, 18]},
        ],
        "stories": [
            {"id": "US9", "epic_id": "E8", "title": "Ingest website applications",
             "as_a": "loan operations analyst", "i_want": "website applications captured automatically",
             "so_that": "applicant details are not re-keyed",
             "acceptance_criteria": [
                 {"given": "a complete website application", "when": "it is submitted",
                  "then": "its applicant data is recorded once in the intake system"},
                 {"given": "a recorded website application", "when": "operations opens it",
                  "then": "the source is identified as website"},
             ],
             "requirement_ids": ["R1"], "evidence_utterances": [2, 3, 5]},
            {"id": "US10", "epic_id": "E9", "title": "Route incomplete applications",
             "as_a": "senior underwriter", "i_want": "incomplete applications in a manual queue",
             "so_that": "missing documents can be resolved",
             "acceptance_criteria": [
                 {"given": "an application missing a required document", "when": "validation completes",
                  "then": "the application is placed in the manual review queue"},
             ],
             "requirement_ids": ["R3"], "evidence_utterances": [8, 21]},
        ],
    }


def test_story_generation_validates_traceability_and_persists(tmp_path) -> None:
    store, session_id = _session(tmp_path)
    service = StoryService(store, MockProvider([_response()]))

    result = service.generate(session_id)

    package = result["package"]
    assert package["revision"] == 1
    assert [epic["id"] for epic in package["epics"]] == ["E1", "E2"]
    assert [story["id"] for story in package["stories"]] == ["US1", "US2"]
    assert package["epics"][0]["evidence_utterances"] == [5, 14]
    assert package["stories"][0]["acceptance_criteria"][0]["id"] == "US1-AC1"
    assert DeliveryRepository(store).load(session_id) == package


def test_regeneration_repairs_provider_id_drift_and_preserves_criteria_ids(tmp_path) -> None:
    store, session_id = _session(tmp_path)
    first = _response()
    second = copy.deepcopy(first)
    second["epics"][0]["id"] = "E99"
    second["epics"][1]["id"] = "E98"
    second["stories"][0]["id"] = "US99"
    second["stories"][0]["epic_id"] = "E99"
    second["stories"][1]["id"] = "US98"
    second["stories"][1]["epic_id"] = "E98"
    service = StoryService(store, MockProvider([first, second]))

    initial = service.generate(session_id)["package"]
    regenerated = service.generate(session_id)["package"]

    assert [e["id"] for e in regenerated["epics"]] == ["E1", "E2"]
    assert [s["id"] for s in regenerated["stories"]] == ["US1", "US2"]
    assert regenerated["stories"][0]["acceptance_criteria"][0]["id"] == \
        initial["stories"][0]["acceptance_criteria"][0]["id"]
    assert regenerated["revision"] == 2


def test_story_edits_merge_delete_and_revision_persist(tmp_path) -> None:
    store, session_id = _session(tmp_path)
    service = StoryService(store, MockProvider([_response()]))
    service.generate(session_id)

    edited = service.update_story(session_id, "US1", {"title": "Capture web applications"})
    assert edited["stories"][0]["title"] == "Capture web applications"
    merged = service.merge_stories(session_id, "US1", ["US2"])
    assert [s["id"] for s in merged["stories"]] == ["US1"]
    assert "R3" in merged["stories"][0]["requirement_ids"]
    assert len(merged["stories"][0]["acceptance_criteria"]) == 3
    without_story = service.delete_story(session_id, "US1")
    assert without_story["stories"] == []
    without_epic = service.delete_epic(session_id, "E2")
    assert [e["id"] for e in without_epic["epics"]] == ["E1"]
    assert without_epic["revision"] == 5


def test_invalid_edit_is_rejected_without_overwriting_package(tmp_path) -> None:
    store, session_id = _session(tmp_path)
    service = StoryService(store, MockProvider([_response()]))
    original = service.generate(session_id)["package"]

    with pytest.raises(DeliveryValidationError):
        service.update_story(session_id, "US1", {"epic_id": "E404"})

    assert service.get(session_id) == original

