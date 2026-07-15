from __future__ import annotations

from src.intelligence.engine import IntelligenceEngine
from src.intelligence.providers import MockProvider
from src.intelligence.state import Utterance, empty_state
from src.sessions.store import SessionStore
from tests.fixtures.meeting_transcript import pass1_state, pass2_state, utterances


def _store_with(tmp_path, items: list[Utterance]) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session()
    for item in items:
        store.append_utterance(session_id, item)
    return store, session_id


def test_cadence_and_incremental_context_with_stable_ids(tmp_path) -> None:
    all_utterances = utterances()
    store, session_id = _store_with(tmp_path, all_utterances[:6])
    provider = MockProvider([pass1_state(), pass2_state()])
    engine = IntelligenceEngine(provider, store, min_gap_seconds=15,
                                content_trigger_seconds=1000, utterance_trigger=6)

    first = engine.maybe_analyze(session_id, now=100)
    assert first is not None
    assert store.load_state(session_id)[1] == 1
    assert engine.maybe_analyze(session_id, now=101) is None

    for item in all_utterances[6:12]:
        store.append_utterance(session_id, item)
    assert engine.maybe_analyze(session_id, now=110) is None
    second = engine.maybe_analyze(session_id, now=116)

    assert second is not None
    assert second["requirements"][0]["id"] == "R1"
    assert second["diagrams"][0]["id"] == "G1"
    assert "[U7 @" in provider.calls[1]["user"]
    assert "[U1 @" in provider.calls[1]["user"]
    assert store.load_analysis_watermark(session_id) == 12


def test_server_repairs_provider_id_drift(tmp_path) -> None:
    store, session_id = _store_with(tmp_path, [Utterance(1, 0, 1, "retain seven years")])
    previous = empty_state()
    previous["requirements"] = [
        {"id": "R1", "text": "Retain records for seven years.", "status": "captured",
         "evidence_utterances": [1]},
    ]
    store.snapshot_state(session_id, previous, 1, analyzed_through=0)
    drifted = empty_state()
    drifted["requirements"] = [
        {"id": "R8", "text": "Retain records for seven years.", "status": "confirmed",
         "evidence_utterances": [1]},
    ]
    engine = IntelligenceEngine(MockProvider([drifted]), store)

    state = engine.analyze(session_id, now=1)

    assert state["requirements"][0]["id"] == "R1"


def test_dismiss_and_edit_overrides_survive_later_pass(tmp_path) -> None:
    store, session_id = _store_with(tmp_path, utterances()[:2])
    previous = pass1_state()
    store.snapshot_state(session_id, previous, 1, analyzed_through=0)
    store.append_override(session_id, {"kind": "requirement", "id": "R2",
                                           "action": "dismiss"})
    store.append_override(session_id, {"kind": "requirement", "id": "R1",
                                           "action": "edit", "text": "Analyst-approved wording",
                                           "status": "confirmed"})
    response = pass2_state()
    response["requirements"] = [item for item in response["requirements"]
                                if item["id"] != "R1"]
    provider = MockProvider([response])

    state = IntelligenceEngine(provider, store).analyze(session_id, now=1)

    ids = {item["id"] for item in state["requirements"]}
    assert "R2" not in ids
    edited = next(item for item in state["requirements"] if item["id"] == "R1")
    assert edited["text"] == "Analyst-approved wording"
    assert edited["status"] == "confirmed"
    assert "do NOT re-raise" in provider.calls[0]["user"]
    assert "requirements/R2" in provider.calls[0]["user"]


def test_invalid_mermaid_is_converted_to_gap(tmp_path) -> None:
    store, session_id = _store_with(tmp_path, [Utterance(1, 0, 1, "A then B")])
    response = empty_state()
    response["diagrams"] = [{
        "id": "G1", "kind": "flowchart", "title": "Bad",
        "mermaid": "flowchart TD\nA[unquoted] --> B[\"B\"]", "evidence_utterances": [1],
    }]

    state = IntelligenceEngine(MockProvider([response]), store).analyze(session_id)

    assert state["diagrams"] == []
    assert state["gaps"][0]["id"] == "X1"
    assert "dropped as invalid" in state["gaps"][0]["text"]


def test_restart_uses_persisted_analysis_watermark(tmp_path) -> None:
    items = [Utterance(i, float(i), float(i + 1), f"utterance {i}") for i in range(1, 7)]
    store, session_id = _store_with(tmp_path, items)
    first = IntelligenceEngine(MockProvider([empty_state()]), store,
                               utterance_trigger=6, content_trigger_seconds=1000)
    assert first.maybe_analyze(session_id, now=1) is not None

    restarted_provider = MockProvider([empty_state()])
    restarted = IntelligenceEngine(restarted_provider, SessionStore(tmp_path / "data"),
                                   utterance_trigger=1, content_trigger_seconds=0)
    assert restarted.maybe_analyze(session_id, now=100) is None
    assert restarted_provider.calls == []


def test_provider_failure_does_not_advance_revision_or_watermark(tmp_path) -> None:
    store, session_id = _store_with(tmp_path, [Utterance(1, 0, 1, "one")])
    engine = IntelligenceEngine(MockProvider([]), store)
    assert engine.analyze(session_id) is None
    assert store.load_state(session_id)[1] == 0
    assert store.load_analysis_watermark(session_id) == -1


def test_retired_item_id_is_not_reused_even_after_restart(tmp_path) -> None:
    store, session_id = _store_with(tmp_path, [Utterance(1, 0, 1, "one")])
    first = empty_state()
    first["requirements"] = [
        {"id": "R1", "text": "First", "status": "captured", "evidence_utterances": [1]},
        {"id": "R2", "text": "Retire me", "status": "captured", "evidence_utterances": [1]},
    ]
    after_retirement = empty_state()
    after_retirement["requirements"] = [first["requirements"][0]]
    with_new_item = empty_state()
    with_new_item["requirements"] = [
        first["requirements"][0],
        {"id": "R2", "text": "Genuinely new", "status": "captured",
         "evidence_utterances": []},
    ]
    engine = IntelligenceEngine(MockProvider([first, after_retirement]), store)
    engine.analyze(session_id, now=1)
    engine.analyze(session_id, now=2)

    restarted = IntelligenceEngine(MockProvider([with_new_item]),
                                   SessionStore(tmp_path / "data"))
    state = restarted.analyze(session_id, now=3)

    assert [item["id"] for item in state["requirements"]] == ["R1", "R3"]
