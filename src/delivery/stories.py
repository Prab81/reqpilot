"""Story generation and analyst-edit lifecycle."""
from __future__ import annotations

import copy
from typing import Any

from src.delivery.models import DeliveryValidationError, build_package, validate_package
from src.delivery.repository import DeliveryRepository
from src.delivery.story_prompts import STORY_SCHEMA_HINT, build_story_prompt
from src.intelligence.providers import LlmProvider
from src.sessions.store import SessionStore


class StoryService:
    def __init__(self, store: SessionStore, provider: LlmProvider,
                 repo: DeliveryRepository | None = None) -> None:
        self.store = store
        self.provider = provider
        self.repo = repo or DeliveryRepository(store)

    def generate(self, session_id: str) -> dict[str, Any]:
        session = self.store.load_session(session_id)
        previous = self.repo.load(session_id) if self.repo.exists(session_id) else None
        system, user = build_story_prompt(session["state"], session["utterances"], previous)
        response = self.provider.complete_json(system, user, STORY_SCHEMA_HINT, max_tokens=8192)
        package, problems = build_package(
            response,
            title=session["state"].get("title", "") or session["meta"].get("title", ""),
            requirement_ids={str(r.get("id")) for r in session["state"].get("requirements", [])},
            utterance_ids={u.id for u in session["utterances"]},
            previous=previous,
        )
        package = self.repo.save(session_id, package)
        return {"package": package, "warnings": problems}

    def get(self, session_id: str) -> dict[str, Any]:
        return self.repo.load(session_id)

    def update_epic(self, session_id: str, epic_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        package = copy.deepcopy(self.repo.load(session_id))
        epic = _find(package["epics"], epic_id, "epic")
        _apply_text_patch(epic, patch, {"title", "description"})
        for field in ("requirement_ids", "evidence_utterances"):
            if field in patch:
                epic[field] = _dedupe_list(patch[field], field)
        return self.repo.save(session_id, package)

    def update_story(self, session_id: str, story_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        package = copy.deepcopy(self.repo.load(session_id))
        story = _find(package["stories"], story_id, "story")
        _apply_text_patch(story, patch, {"title", "as_a", "i_want", "so_that"})
        if "epic_id" in patch:
            if patch["epic_id"] not in {e["id"] for e in package["epics"]}:
                raise DeliveryValidationError("unknown epic_id")
            story["epic_id"] = patch["epic_id"]
        for field in ("requirement_ids", "evidence_utterances"):
            if field in patch:
                story[field] = _dedupe_list(patch[field], field)
        if "acceptance_criteria" in patch:
            story["acceptance_criteria"] = _edited_criteria(story_id, patch["acceptance_criteria"])
        validate_package(package)
        return self.repo.save(session_id, package)

    def merge_stories(self, session_id: str, target_id: str,
                      source_ids: list[str]) -> dict[str, Any]:
        package = copy.deepcopy(self.repo.load(session_id))
        target = _find(package["stories"], target_id, "story")
        source_ids = [value for value in dict.fromkeys(source_ids) if value != target_id]
        if not source_ids:
            raise DeliveryValidationError("at least one different source story is required")
        sources = [_find(package["stories"], value, "story") for value in source_ids]
        target["requirement_ids"] = _union(target, sources, "requirement_ids")
        target["evidence_utterances"] = _union(target, sources, "evidence_utterances")
        seen = {"|".join(str(c.get(k, "")).casefold() for k in ("given", "when", "then"))
                for c in target["acceptance_criteria"]}
        next_number = max((int(c["id"].rsplit("AC", 1)[1]) for c in target["acceptance_criteria"]), default=0)
        for source in sources:
            for criterion in source["acceptance_criteria"]:
                signature = "|".join(str(criterion.get(k, "")).casefold() for k in ("given", "when", "then"))
                if signature in seen:
                    continue
                next_number += 1
                target["acceptance_criteria"].append({**criterion, "id": f"{target_id}-AC{next_number}"})
                seen.add(signature)
        package["stories"] = [s for s in package["stories"] if s["id"] not in source_ids]
        return self.repo.save(session_id, package)

    def delete_story(self, session_id: str, story_id: str) -> dict[str, Any]:
        package = copy.deepcopy(self.repo.load(session_id))
        _find(package["stories"], story_id, "story")
        package["stories"] = [s for s in package["stories"] if s["id"] != story_id]
        return self.repo.save(session_id, package)

    def delete_epic(self, session_id: str, epic_id: str) -> dict[str, Any]:
        package = copy.deepcopy(self.repo.load(session_id))
        _find(package["epics"], epic_id, "epic")
        package["epics"] = [e for e in package["epics"] if e["id"] != epic_id]
        package["stories"] = [s for s in package["stories"] if s["epic_id"] != epic_id]
        return self.repo.save(session_id, package)


def _find(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    item = next((value for value in items if value.get("id") == item_id), None)
    if item is None:
        raise DeliveryValidationError(f"unknown {kind} {item_id!r}")
    return item


def _apply_text_patch(item: dict[str, Any], patch: dict[str, Any], fields: set[str]) -> None:
    if not isinstance(patch, dict):
        raise DeliveryValidationError("patch must be an object")
    for field in fields:
        if field in patch:
            if not isinstance(patch[field], str) or not patch[field].strip():
                raise DeliveryValidationError(f"{field} must be a non-empty string")
            item[field] = patch[field].strip()


def _dedupe_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise DeliveryValidationError(f"{field} must be a list")
    result: list[Any] = []
    for item in value:
        if item not in result:
            result.append(item)
    return result


def _edited_criteria(story_id: str, value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise DeliveryValidationError("acceptance_criteria must be a non-empty list")
    result: list[dict[str, str]] = []
    used: set[str] = set()
    high = 0
    for raw in value:
        if not isinstance(raw, dict):
            raise DeliveryValidationError("each acceptance criterion must be an object")
        fields = {key: str(raw.get(key, "")).strip() for key in ("given", "when", "then")}
        if not all(fields.values()):
            raise DeliveryValidationError("acceptance criteria require given, when, and then")
        candidate = str(raw.get("id", ""))
        if candidate.startswith(f"{story_id}-AC") and candidate not in used:
            ac_id = candidate
            try:
                high = max(high, int(candidate.rsplit("AC", 1)[1]))
            except ValueError:
                ac_id = ""
        else:
            ac_id = ""
        if not ac_id:
            high += 1
            ac_id = f"{story_id}-AC{high}"
        used.add(ac_id)
        result.append({"id": ac_id, **fields})
    return result


def _union(target: dict[str, Any], sources: list[dict[str, Any]], field: str) -> list[Any]:
    result: list[Any] = []
    for value in [target, *sources]:
        for item in value.get(field, []):
            if item not in result:
                result.append(item)
    return result

