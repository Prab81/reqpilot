from __future__ import annotations

import json

import httpx

from src.delivery import JiraCloudClient, JiraConfig, JiraSyncService
from src.delivery.repository import DeliveryRepository
from src.sessions.store import SessionStore


def _package() -> dict:
    return {
        "version": 1, "revision": 0, "generated_at": "2026-07-16T00:00:00Z",
        "title": "Loan intake", "high_water": {"epics": 1, "stories": 1},
        "epics": [{
            "id": "E1", "title": "Digital intake", "description": "Capture applications once.",
            "requirement_ids": ["R1"], "evidence_utterances": [5],
        }],
        "stories": [{
            "id": "US1", "epic_id": "E1", "title": "Ingest website applications",
            "as_a": "loan operations analyst", "i_want": "website applications captured automatically",
            "so_that": "details are not re-keyed", "requirement_ids": ["R1"],
            "evidence_utterances": [2, 5],
            "acceptance_criteria": [{
                "id": "US1-AC1", "given": "a valid application", "when": "it is submitted",
                "then": "its data is captured once",
            }],
        }],
    }


def _repo(tmp_path) -> tuple[DeliveryRepository, str]:
    store = SessionStore(tmp_path / "data")
    sid = store.create_session()
    repo = DeliveryRepository(store)
    repo.save(sid, _package())
    return repo, sid


def _client(handler) -> JiraCloudClient:
    return JiraCloudClient(
        JiraConfig("https://example.atlassian.net", "analyst@example.com", "super-secret", "LOAN"),
        transport=httpx.MockTransport(handler),
    )


def test_preview_is_side_effect_free_and_uses_modern_parent_semantics(tmp_path) -> None:
    repo, sid = _repo(tmp_path)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("preview must not call Jira")

    preview = JiraSyncService(repo, _client(handler)).preview(sid)

    assert calls == []
    assert preview["counts"] == {"create": 2, "update": 0, "skip": 0}
    story = next(op for op in preview["operations"] if op["kind"] == "story")
    assert story["fields"]["parent"] == {"key": "{{E1.key}}"}
    assert "Epic Link" not in json.dumps(story["fields"])


def test_selected_preview_exports_only_requested_stories_and_their_parent(tmp_path) -> None:
    repo, sid = _repo(tmp_path)
    preview = JiraSyncService(repo, _client(lambda request: httpx.Response(500))).preview(
        sid, story_ids=["US1"]
    )

    assert [(op["kind"], op["local_id"]) for op in preview["operations"]] == [
        ("epic", "E1"), ("story", "US1")
    ]


def test_sync_creates_epic_then_story_and_second_sync_is_idempotent(tmp_path) -> None:
    repo, sid = _repo(tmp_path)
    requests: list[tuple[str, str, dict | None]] = []
    created = iter([("10001", "LOAN-1"), ("10002", "LOAN-2")])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.method == "POST":
            issue_id, key = next(created)
            return httpx.Response(201, json={"id": issue_id, "key": key})
        if request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404)

    service = JiraSyncService(repo, _client(handler))
    first = service.sync(sid)
    second = service.sync(sid)

    assert [op["action"] for op in first["operations"]] == ["create", "create"]
    assert [op["action"] for op in second["operations"]] == ["skip", "skip"]
    assert len(requests) == 2
    assert requests[0][1] == "/rest/api/3/issue"
    assert requests[0][2]["fields"]["issuetype"] == {"name": "Epic"}
    assert requests[1][2]["fields"]["parent"] == {"key": "LOAN-1"}
    assert repo.load_jira_mapping(sid)["issues"]["US1"]["key"] == "LOAN-2"


def test_sync_updates_only_changed_issue(tmp_path) -> None:
    repo, sid = _repo(tmp_path)
    requests: list[httpx.Request] = []
    next_key = iter(["LOAN-1", "LOAN-2"])

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            key = next(next_key)
            return httpx.Response(201, json={"id": key.split("-")[1], "key": key})
        return httpx.Response(204)

    service = JiraSyncService(repo, _client(handler))
    service.sync(sid)
    package = repo.load(sid)
    package["stories"][0]["title"] = "Capture website applications"
    repo.save(sid, package)
    result = service.sync(sid)

    assert [op["action"] for op in result["operations"]] == ["skip", "update"]
    assert requests[-1].method == "PUT"
    assert requests[-1].url.path == "/rest/api/3/issue/LOAN-2"


def test_status_never_exposes_api_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/myself"):
            return httpx.Response(200, json={"accountId": "a1", "displayName": "Analyst"})
        return httpx.Response(200, json={"id": "p1", "key": "LOAN"})

    status = _client(handler).status()

    assert status["reachable"] is True
    assert status["project"]["key"] == "LOAN"
    assert "super-secret" not in json.dumps(status)
    assert "api_token" not in status
