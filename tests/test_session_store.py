from __future__ import annotations

import json

import pytest

from src.intelligence.state import Utterance, empty_state
from src.sessions.store import SessionStore


def test_session_survives_store_restart_with_transcript_state_and_overrides(tmp_path) -> None:
    data_dir = tmp_path / "reqpilot-data"
    store = SessionStore(data_dir)
    session_id = store.create_session()
    store.append_utterance(session_id, Utterance(1, 0.25, 3.5, "hello"))
    state = empty_state()
    state["title"] = "Recovered title"
    store.snapshot_state(session_id, state, 4, analyzed_through=1)
    store.append_override(session_id, {"kind": "question", "id": "Q1", "action": "parked"})

    loaded = SessionStore(data_dir).load_session(session_id)

    assert loaded["utterances"] == [Utterance(1, 0.25, 3.5, "hello")]
    assert loaded["state"] == state
    assert loaded["rev"] == 4
    assert loaded["overrides"][0]["id"] == "Q1"
    assert SessionStore(data_dir).load_analysis_watermark(session_id) == 1
    assert SessionStore(data_dir).list_sessions()[0]["title"] == "Recovered title"


def test_torn_final_jsonl_record_is_ignored(tmp_path) -> None:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session()
    store.append_utterance(session_id, Utterance(1, 0, 1, "safe"))
    path = store.session_dir(session_id) / "utterances.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"id": 2, "t0":')
    store.append_utterance(session_id, Utterance(3, 2, 3, "after restart"))

    assert store.load_utterances(session_id) == [
        Utterance(1, 0, 1, "safe"), Utterance(3, 2, 3, "after restart"),
    ]


@pytest.mark.parametrize("bad_id", ["../escape", "..", "a/b", "a\\b", "", ".hidden"])
def test_session_id_cannot_escape_local_data_directory(tmp_path, bad_id: str) -> None:
    store = SessionStore(tmp_path / "data")
    with pytest.raises(ValueError):
        store.session_dir(bad_id)


def test_all_artifacts_are_under_configured_data_dir(tmp_path) -> None:
    data_dir = tmp_path / "only-here"
    store = SessionStore(data_dir)
    session_id = store.create_session("Title")
    store.append_utterance(session_id, Utterance(1, 0, 1, "local"))
    store.snapshot_state(session_id, empty_state(), 1)
    store.append_override(session_id, {"kind": "requirement", "id": "R1", "action": "pin"})

    files = {path.name for path in data_dir.rglob("*") if path.is_file()}
    assert files == {"meta.json", "utterances.jsonl", "state.json", "overrides.jsonl"}
    assert all(data_dir.resolve() in path.resolve().parents
               for path in data_dir.rglob("*") if path.is_file())


def test_atomic_snapshot_leaves_no_temp_file(tmp_path) -> None:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session()
    store.snapshot_state(session_id, empty_state(), 1)
    session_dir = store.session_dir(session_id)
    assert json.loads((session_dir / "state.json").read_text(encoding="utf-8"))["rev"] == 1
    assert list(session_dir.glob("*.tmp")) == []


def test_manual_snapshot_preserves_engine_restart_metadata(tmp_path) -> None:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session()
    store.snapshot_state(session_id, empty_state(), 1, analyzed_through=7,
                         id_high_water={"requirements": 4})
    store.snapshot_state(session_id, empty_state(), 2)
    assert store.load_analysis_watermark(session_id) == 7
    assert store.load_id_high_water(session_id) == {"requirements": 4}
