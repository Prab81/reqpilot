from __future__ import annotations

from src.intelligence.brd import generate_brd
from src.intelligence.providers import MockProvider
from src.sessions.store import SessionStore
from tests.fixtures.meeting_transcript import brd_narrative, pass2_state, utterances


def _session(tmp_path) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session()
    for item in utterances():
        store.append_utterance(session_id, item)
    store.snapshot_state(session_id, pass2_state(), 2, analyzed_through=30)
    return store, session_id


def test_brd_has_all_sections_requirements_and_real_evidence(tmp_path) -> None:
    store, session_id = _session(tmp_path)

    markdown = generate_brd(session_id, store, MockProvider([brd_narrative()]))

    for heading in (
        "## 1. Context & Background", "## 2. Stakeholders",
        "## 3. Current Process", "## 4. Future Process",
        "## 5. Functional Requirements", "## 6. Non-Functional Requirements",
        "## 7. Assumptions", "## 8. Open Items",
    ):
        assert heading in markdown
    for requirement in pass2_state()["requirements"]:
        assert f"| {requirement['id']} |" in markdown
    assert "[00:08]" in markdown
    assert "[99:99]" not in markdown
    assert "```mermaid" in markdown


def test_brd_degrades_to_deterministic_state_only_document(tmp_path) -> None:
    store, session_id = _session(tmp_path)

    markdown = generate_brd(session_id, store, MockProvider([]))

    assert markdown.startswith("# Consumer Loan Application Processing")
    assert "_Not captured._" in markdown
    assert "| R14 |" in markdown
    assert "[03:45]" in markdown
