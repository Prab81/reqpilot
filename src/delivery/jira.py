"""Jira Cloud v3 client and idempotent delivery-package synchronization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from src.delivery.models import DeliveryValidationError
from src.delivery.repository import DeliveryRepository


class JiraError(RuntimeError):
    """Safe Jira failure that never embeds authorization credentials."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True, slots=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    project_key: str
    epic_issue_type: str = "Epic"
    story_issue_type: str = "Story"

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("Jira base_url must be an HTTP(S) URL")
        if not self.project_key.strip():
            raise ValueError("Jira project_key is required")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url.rstrip("/"),
            "email": self.email,
            "project_key": self.project_key,
            "epic_issue_type": self.epic_issue_type,
            "story_issue_type": self.story_issue_type,
            "configured": bool(self.base_url and self.email and self.api_token and self.project_key),
        }


class JiraCloudClient:
    def __init__(self, config: JiraConfig,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            auth=(config.email, config.api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def status(self) -> dict[str, Any]:
        """Check account and project access, returning only safe metadata."""
        try:
            account = self._request("GET", "/rest/api/3/myself")
            project = self._request("GET", f"/rest/api/3/project/{self.config.project_key}")
        except JiraError as exc:
            return {
                **self.config.safe_dict(),
                "reachable": False,
                "error": str(exc),
                "status_code": exc.status_code,
            }
        return {
            **self.config.safe_dict(),
            "reachable": True,
            "account": {
                "account_id": account.get("accountId", ""),
                "display_name": account.get("displayName", ""),
            },
            "project": {"id": project.get("id", ""), "key": project.get("key", "")},
        }

    def create_issue(self, fields: dict[str, Any]) -> dict[str, str]:
        result = self._request("POST", "/rest/api/3/issue", json_body={"fields": fields})
        key = str(result.get("key", ""))
        issue_id = str(result.get("id", ""))
        if not key:
            raise JiraError("Jira create response did not include an issue key")
        return {"key": key, "id": issue_id}

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> None:
        self._request("PUT", f"/rest/api/3/issue/{issue_key}", json_body={"fields": fields},
                      allow_empty=True)

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None,
                 allow_empty: bool = False) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, json=json_body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            details: Any = None
            try:
                details = exc.response.json()
            except (ValueError, json.JSONDecodeError):
                details = exc.response.text[:500]
            raise JiraError(
                f"Jira {method} {path} failed with HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                details=details,
            ) from exc
        except httpx.HTTPError as exc:
            raise JiraError(f"Jira {method} {path} could not be completed: {exc}") from exc
        if allow_empty and not response.content:
            return {}
        try:
            value = response.json()
        except json.JSONDecodeError as exc:
            if allow_empty:
                return {}
            raise JiraError(f"Jira {method} {path} returned invalid JSON",
                            status_code=response.status_code) from exc
        if not isinstance(value, dict):
            raise JiraError(f"Jira {method} {path} returned an unexpected response",
                            status_code=response.status_code)
        return value


class JiraSyncService:
    """Plan or apply create/update operations with persisted local mappings."""

    def __init__(self, repo: DeliveryRepository, client: JiraCloudClient) -> None:
        self.repo = repo
        self.client = client

    def preview(self, session_id: str,
                story_ids: list[str] | None = None) -> dict[str, Any]:
        package = self._selected_package(self.repo.load(session_id), story_ids)
        mapping = self.repo.load_jira_mapping(session_id)
        operations = self._preview_operations(package, mapping)
        return {
            "dry_run": True,
            "project_key": self.client.config.project_key,
            "operations": operations,
            "counts": _counts(operations),
        }

    def sync(self, session_id: str, dry_run: bool = False,
             story_ids: list[str] | None = None) -> dict[str, Any]:
        if dry_run:
            return self.preview(session_id, story_ids=story_ids)
        package = self._selected_package(self.repo.load(session_id), story_ids)
        mapping = self.repo.load_jira_mapping(session_id)
        issue_map = mapping.setdefault("issues", {})
        results: list[dict[str, Any]] = []

        # Epics must exist before stories so modern Jira's parent.key can link them.
        for epic in package["epics"]:
            fields = self._epic_fields(epic)
            results.append(self._apply(epic["id"], "epic", fields, issue_map, session_id, mapping))
        for story in package["stories"]:
            parent = issue_map.get(story["epic_id"], {}).get("key")
            if not parent:
                raise JiraError(f"cannot sync {story['id']}: epic {story['epic_id']} has no Jira key")
            fields = self._story_fields(story, parent)
            results.append(self._apply(story["id"], "story", fields, issue_map, session_id, mapping))
        return {
            "dry_run": False,
            "project_key": self.client.config.project_key,
            "operations": results,
            "counts": _counts(results),
            "mapping": mapping,
        }

    @staticmethod
    def _selected_package(package: dict[str, Any],
                          story_ids: list[str] | None) -> dict[str, Any]:
        if story_ids is None:
            return package
        if not isinstance(story_ids, list) or not all(isinstance(value, str) for value in story_ids):
            raise DeliveryValidationError("story_ids must be a list of story IDs")
        wanted = set(story_ids)
        known = {story["id"] for story in package["stories"]}
        unknown = wanted - known
        if unknown:
            raise DeliveryValidationError(f"unknown story IDs: {', '.join(sorted(unknown))}")
        selected = [story for story in package["stories"] if story["id"] in wanted]
        parent_ids = {story["epic_id"] for story in selected}
        return {
            **package,
            "epics": [epic for epic in package["epics"] if epic["id"] in parent_ids],
            "stories": selected,
        }

    def _preview_operations(self, package: dict[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
        issues = mapping.get("issues", {})
        operations: list[dict[str, Any]] = []
        for epic in package["epics"]:
            fields = self._epic_fields(epic)
            operations.append(self._planned(epic["id"], "epic", fields, issues.get(epic["id"])))
        for story in package["stories"]:
            parent = issues.get(story["epic_id"], {}).get("key") or f"{{{{{story['epic_id']}.key}}}}"
            fields = self._story_fields(story, parent)
            operations.append(self._planned(story["id"], "story", fields, issues.get(story["id"])))
        return operations

    def _apply(self, local_id: str, kind: str, fields: dict[str, Any],
               issues: dict[str, Any], session_id: str,
               mapping: dict[str, Any]) -> dict[str, Any]:
        digest = _digest(fields)
        current = issues.get(local_id)
        if current and current.get("content_hash") == digest:
            return {"local_id": local_id, "kind": kind, "action": "skip", "jira_key": current.get("key")}
        if current and current.get("key"):
            self.client.update_issue(str(current["key"]), fields)
            current.update({"content_hash": digest, "kind": kind})
            self.repo.save_jira_mapping(session_id, mapping)
            return {"local_id": local_id, "kind": kind, "action": "update", "jira_key": current["key"]}
        created = self.client.create_issue(fields)
        issues[local_id] = {**created, "content_hash": digest, "kind": kind}
        self.repo.save_jira_mapping(session_id, mapping)
        return {"local_id": local_id, "kind": kind, "action": "create", "jira_key": created["key"]}

    def _planned(self, local_id: str, kind: str, fields: dict[str, Any],
                 current: dict[str, Any] | None) -> dict[str, Any]:
        digest = _digest(fields)
        if current and current.get("content_hash") == digest:
            action = "skip"
        elif current and current.get("key"):
            action = "update"
        else:
            action = "create"
        return {
            "local_id": local_id,
            "kind": kind,
            "action": action,
            "jira_key": current.get("key") if current else None,
            "fields": fields,
        }

    def _epic_fields(self, epic: dict[str, Any]) -> dict[str, Any]:
        body = [epic["description"]]
        body += _traceability_lines(epic)
        return {
            "project": {"key": self.client.config.project_key},
            "issuetype": {"name": self.client.config.epic_issue_type},
            "summary": epic["title"],
            "description": _adf(body),
        }

    def _story_fields(self, story: dict[str, Any], parent_key: str) -> dict[str, Any]:
        body = [
            f"As a {story['as_a']}, I want {story['i_want']}, so that {story['so_that']}.",
            "Acceptance criteria:",
        ]
        for criterion in story["acceptance_criteria"]:
            body.append(
                f"{criterion['id']}: Given {criterion['given']}; "
                f"when {criterion['when']}; then {criterion['then']}."
            )
        body += _traceability_lines(story)
        return {
            "project": {"key": self.client.config.project_key},
            "issuetype": {"name": self.client.config.story_issue_type},
            "summary": story["title"],
            "description": _adf(body),
            "parent": {"key": parent_key},
        }


def _traceability_lines(item: dict[str, Any]) -> list[str]:
    requirements = ", ".join(item.get("requirement_ids", [])) or "none"
    evidence = ", ".join(f"U{value}" for value in item.get("evidence_utterances", [])) or "none"
    return [f"ReqPilot requirements: {requirements}", f"Transcript evidence: {evidence}"]


def _adf(paragraphs: list[str]) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            for text in paragraphs if text
        ],
    }


def _digest(fields: dict[str, Any]) -> str:
    encoded = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _counts(operations: list[dict[str, Any]]) -> dict[str, int]:
    return {action: sum(1 for item in operations if item.get("action") == action)
            for action in ("create", "update", "skip")}
