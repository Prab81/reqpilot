from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from src.delivery import JiraCloudClient, JiraConfig
from src.importers import MAX_IMPORT_BYTES
from src.intelligence.providers import MockProvider
from src.intelligence.state import Utterance, empty_state
from src.server import create_app
from src.sessions.store import SessionStore


FIXTURES = Path(__file__).parent / "fixtures"


def analyzed_state():
    state = empty_state()
    state["title"] = "Imported discovery"
    state["summary"] = ["Applications require a decision within 24 hours."]
    state["requirements"] = [{
        "id": "R1",
        "text": "Applications receive a decision within 24 hours.",
        "status": "captured",
        "evidence_utterances": [1],
    }]
    return state


def build(tmp_path, responses=None):
    store = SessionStore(tmp_path / "data")
    provider = MockProvider(list(responses or []))
    client = TestClient(create_app(store=store, provider=provider))
    return client, store, provider


def test_upload_vtt_creates_persists_analyzes_and_returns_transcript(tmp_path) -> None:
    client, store, provider = build(tmp_path, [analyzed_state()])
    payload = (FIXTURES / "teams_transcript.vtt").read_bytes()

    response = client.post(
        "/api/session/import",
        data={"title": "Teams workshop"},
        files={"file": ("teams.vtt", payload, "text/vtt")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert body["rev"] == 1
    assert body["session"]["title"] == "Teams workshop"
    assert body["session"]["format"] == "vtt"
    session_id = body["session"]["id"]
    assert store.load_utterances(session_id)[0].text.startswith("Priya Shah:")
    assert "Priya Shah:" in provider.calls[0]["user"]

    transcript = client.get(f"/api/session/{session_id}/transcript")
    assert transcript.status_code == 200
    assert transcript.json()["count"] == 3
    assert transcript.json()["utterances"][0]["t0"] == 2.25
    assert client.get(f"/api/session/{session_id}/state").json() == body["state"]


def test_pasted_text_with_filename_and_title_uses_same_pipeline(tmp_path) -> None:
    client, _store, _provider = build(tmp_path, [analyzed_state()])
    source = (FIXTURES / "copilot_recap.txt").read_text(encoding="utf-8")

    response = client.post("/api/session/import", data={
        "text": source, "filename": "copilot.txt", "title": "Copilot recap",
    })

    assert response.status_code == 200
    assert response.json()["count"] == 3
    assert response.json()["session"]["filename"] == "copilot.txt"


def test_pasted_text_defaults_filename_and_title(tmp_path) -> None:
    client, _store, _provider = build(tmp_path, [analyzed_state()])
    response = client.post("/api/session/import", data={"text": "BA: We need exports."})
    assert response.status_code == 200
    assert response.json()["session"]["filename"] == "pasted.txt"
    assert response.json()["session"]["title"] == "pasted"


def test_import_rejects_ambiguous_missing_unsafe_and_unsupported_inputs(tmp_path) -> None:
    client, store, _provider = build(tmp_path)
    assert client.post("/api/session/import", data={}).status_code == 400
    assert client.post(
        "/api/session/import",
        data={"text": "also text"},
        files={"file": ("meeting.txt", b"file text", "text/plain")},
    ).status_code == 400
    assert client.post(
        "/api/session/import", data={"text": "hello", "filename": "../escape.txt"}
    ).status_code == 400
    assert client.post(
        "/api/session/import", files={"file": ("meeting.pdf", b"pdf", "application/pdf")}
    ).status_code == 415
    assert store.list_sessions() == []


def test_import_size_and_title_limits_leave_no_session(tmp_path) -> None:
    client, store, _provider = build(tmp_path)
    oversized = b"x" * (MAX_IMPORT_BYTES + 1)
    response = client.post(
        "/api/session/import", files={"file": ("large.txt", oversized, "text/plain")}
    )
    assert response.status_code == 413

    response = client.post("/api/session/import", data={
        "text": "valid words", "filename": "valid.txt", "title": "x" * 201,
    })
    assert response.status_code == 422
    assert store.list_sessions() == []


def test_analysis_failure_reports_recoverable_persisted_session(tmp_path) -> None:
    client, store, _provider = build(tmp_path)
    response = client.post("/api/session/import", data={
        "text": "Stakeholder: We need an audit trail.", "filename": "notes.txt",
    })

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["session_id"]
    assert store.load_utterances(detail["session_id"])[0].text.startswith("Stakeholder:")


def test_transcript_endpoint_rejects_unknown_and_path_like_ids(tmp_path) -> None:
    client, _store, _provider = build(tmp_path)
    assert client.get("/api/session/not-real/transcript").status_code == 404
    # Encoded traversal must not reach a path outside the configured data directory.
    assert client.get("/api/session/%2E%2E/transcript").status_code in {404, 422}


def story_response():
    return {
        "title": "Audit delivery",
        "epics": [{
            "id": "E1", "title": "Auditability", "description": "Retain history.",
            "requirement_ids": ["R1"], "evidence_utterances": [1],
        }],
        "stories": [{
            "id": "US1", "epic_id": "E1", "title": "View audit history",
            "as_a": "compliance analyst", "i_want": "to view audit events",
            "so_that": "I can investigate changes", "requirement_ids": ["R1"],
            "evidence_utterances": [1], "acceptance_criteria": [{
                "given": "an audit event", "when": "history is opened",
                "then": "the event and actor are shown",
            }],
        }],
    }


def test_delivery_docx_story_and_selected_jira_routes_are_end_to_end(tmp_path) -> None:
    requests: list[httpx.Request] = []
    issue_keys = iter(["AUD-1", "AUD-2"])

    def jira_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "1", "key": next(issue_keys)})

    jira = JiraCloudClient(
        JiraConfig(
            "https://example.atlassian.net", "analyst@example.com",
            "never-return-this-token", "AUD",
        ),
        transport=httpx.MockTransport(jira_handler),
    )
    store = SessionStore(tmp_path / "data")
    provider = MockProvider([story_response()])
    client = TestClient(create_app(store=store, provider=provider, jira_client=jira))
    session_id = store.create_session("Audit workshop")
    store.append_utterance(
        session_id,
        Utterance(1, 1.0, 3.0, "Stakeholder: We need a complete audit trail."),
    )
    state = empty_state()
    state["requirements"] = [{
        "id": "R1", "text": "The system retains a complete audit trail.",
        "status": "captured", "evidence_utterances": [1],
    }]
    store.snapshot_state(session_id, state, 1, analyzed_through=1)

    assert client.get(f"/api/session/{session_id}/stories").json()["stories"] == []
    generated = client.post(f"/api/session/{session_id}/stories/generate")
    assert generated.status_code == 200
    assert generated.json()["package"]["stories"][0]["id"] == "US1"

    preview = client.post(f"/api/session/{session_id}/jira/preview", json={
        "project_key": "AUD", "scope": "selected", "story_ids": ["US1"],
    })
    assert preview.status_code == 200
    assert [item["local_id"] for item in preview.json()["issues"]] == ["E1", "US1"]
    assert requests == []

    exported = client.post(f"/api/session/{session_id}/jira/export", json={
        "project_key": "AUD", "preview": preview.json(),
    })
    assert exported.status_code == 200
    assert exported.json()["created_count"] == 2
    assert len(requests) == 2

    status = client.get("/api/config/status")
    assert status.json()["jira"]["configured"] is True
    assert "never-return-this-token" not in status.text

    # The story call consumed the mock response; DOCX uses its deterministic fallback.
    document = client.get(f"/api/session/{session_id}/brd.docx")
    assert document.status_code == 200
    assert document.content.startswith(b"PK")


def test_jira_preview_is_available_before_credentials_are_configured(
    tmp_path, monkeypatch
) -> None:
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(name, raising=False)
    client, store, _provider = build(tmp_path, [story_response()])
    session_id = store.create_session("Preview-only workshop")
    store.append_utterance(
        session_id,
        Utterance(1, 0.0, 2.0, "Stakeholder: Keep a complete audit trail."),
    )
    state = empty_state()
    state["requirements"] = [{
        "id": "R1", "text": "The system retains a complete audit trail.",
        "status": "captured", "evidence_utterances": [1],
    }]
    store.snapshot_state(session_id, state, 1, analyzed_through=1)
    assert client.post(f"/api/session/{session_id}/stories/generate").status_code == 200

    preview = client.post(
        f"/api/session/{session_id}/jira/preview",
        json={"project_key": "LOCAL", "scope": "all"},
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body["project_key"] == "LOCAL"
    assert [item["local_id"] for item in body["issues"]] == ["E1", "US1"]
    assert all(item["action"] == "create" for item in body["issues"])
