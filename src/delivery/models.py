"""Validated delivery models for epics, user stories, and acceptance criteria.

Provider output is untrusted.  This module turns it into a compact JSON model
whose identifiers remain stable across regeneration and whose evidence always
points at real requirements and transcript utterances.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


class DeliveryValidationError(ValueError):
    """Raised when a delivery package or edit is structurally invalid."""


EPIC_RE = re.compile(r"E[1-9]\d*")
STORY_RE = re.compile(r"US[1-9]\d*")
AC_RE = re.compile(r"US[1-9]\d*-AC[1-9]\d*")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_package(title: str = "") -> dict[str, Any]:
    return {
        "version": 1,
        "revision": 0,
        "generated_at": utc_now(),
        "title": title,
        "epics": [],
        "stories": [],
        "high_water": {"epics": 0, "stories": 0},
    }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique_strings(value: Any, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        item = item.strip()
        if allowed is not None and item not in allowed:
            continue
        if item not in result:
            result.append(item)
    return result


def _unique_ints(value: Any, allowed: set[int]) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool) and item in allowed and item not in result:
            result.append(item)
    return result


def _normal(value: str) -> str:
    return re.sub(r"\W+", " ", value.casefold()).strip()


def _next_id(prefix: str, used: set[str], high: int) -> tuple[str, int]:
    high += 1
    while f"{prefix}{high}" in used:
        high += 1
    return f"{prefix}{high}", high


def build_package(
    response: dict[str, Any],
    *,
    title: str,
    requirement_ids: set[str],
    utterance_ids: set[int],
    previous: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate provider output and assign stable local IDs.

    Invalid records are dropped and reported rather than allowing one malformed
    LLM item to fail the entire post-session generation.
    """
    if not isinstance(response, dict):
        raise DeliveryValidationError("story response must be a JSON object")
    previous = previous or empty_package(title)
    problems: list[str] = []
    prior_epics = [i for i in previous.get("epics", []) if isinstance(i, dict)]
    prior_stories = [i for i in previous.get("stories", []) if isinstance(i, dict)]
    high_water = previous.get("high_water", {}) if isinstance(previous.get("high_water"), dict) else {}
    epic_high = max(
        int(high_water.get("epics", 0) or 0),
        max((int(i["id"][1:]) for i in prior_epics if EPIC_RE.fullmatch(str(i.get("id", "")))), default=0),
    )
    story_high = max(
        int(high_water.get("stories", 0) or 0),
        max((int(i["id"][2:]) for i in prior_stories if STORY_RE.fullmatch(str(i.get("id", "")))), default=0),
    )

    raw_epics = response.get("epics", [])
    if not isinstance(raw_epics, list):
        raise DeliveryValidationError("'epics' must be a list")
    epics: list[dict[str, Any]] = []
    used_epic_ids: set[str] = set()
    provider_epic_map: dict[str, str] = {}
    for index, raw in enumerate(raw_epics, 1):
        if not isinstance(raw, dict):
            problems.append(f"epics/{index}: non-object dropped")
            continue
        epic_title = _text(raw.get("title"))
        description = _text(raw.get("description"))
        if not epic_title or not description:
            problems.append(f"epics/{index}: title and description are required")
            continue
        reqs = _unique_strings(raw.get("requirement_ids"), requirement_ids)
        evidence = _unique_ints(raw.get("evidence_utterances"), utterance_ids)
        provider_id = _text(raw.get("id"))
        match = next((p for p in prior_epics if p.get("id") == provider_id and provider_id not in used_epic_ids), None)
        if match is None:
            match = next((p for p in prior_epics if p.get("id") not in used_epic_ids and _normal(str(p.get("title", ""))) == _normal(epic_title)), None)
        if match is None and reqs:
            matches = [p for p in prior_epics if p.get("id") not in used_epic_ids and set(p.get("requirement_ids", [])) == set(reqs)]
            match = matches[0] if len(matches) == 1 else None
        if match is not None:
            epic_id = str(match["id"])
        else:
            epic_id, epic_high = _next_id("E", used_epic_ids, epic_high)
        used_epic_ids.add(epic_id)
        if provider_id:
            provider_epic_map[provider_id] = epic_id
        epics.append({
            "id": epic_id,
            "title": epic_title,
            "description": description,
            "requirement_ids": reqs,
            "evidence_utterances": evidence,
        })

    raw_stories = response.get("stories", [])
    if not isinstance(raw_stories, list):
        raise DeliveryValidationError("'stories' must be a list")
    stories: list[dict[str, Any]] = []
    used_story_ids: set[str] = set()
    valid_epics = {e["id"] for e in epics}
    for index, raw in enumerate(raw_stories, 1):
        if not isinstance(raw, dict):
            problems.append(f"stories/{index}: non-object dropped")
            continue
        story_title = _text(raw.get("title"))
        as_a = _text(raw.get("as_a"))
        i_want = _text(raw.get("i_want"))
        so_that = _text(raw.get("so_that"))
        epic_ref = provider_epic_map.get(_text(raw.get("epic_id")), _text(raw.get("epic_id")))
        if not story_title or not as_a or not i_want or not so_that or epic_ref not in valid_epics:
            problems.append(f"stories/{index}: title, story sentence, and valid epic_id are required")
            continue
        reqs = _unique_strings(raw.get("requirement_ids"), requirement_ids)
        evidence = _unique_ints(raw.get("evidence_utterances"), utterance_ids)
        criteria_raw = raw.get("acceptance_criteria", [])
        criteria: list[dict[str, str]] = []
        if isinstance(criteria_raw, list):
            for criterion in criteria_raw:
                if not isinstance(criterion, dict):
                    continue
                given, when, then = (_text(criterion.get(k)) for k in ("given", "when", "then"))
                if given and when and then:
                    item = {"given": given, "when": when, "then": then}
                    if item not in criteria:
                        criteria.append(item)
        if not criteria:
            problems.append(f"stories/{index}: at least one Given/When/Then criterion is required")
            continue
        provider_id = _text(raw.get("id"))
        match = next((p for p in prior_stories if p.get("id") == provider_id and provider_id not in used_story_ids), None)
        if match is None:
            match = next((p for p in prior_stories if p.get("id") not in used_story_ids and _normal(str(p.get("title", ""))) == _normal(story_title)), None)
        if match is None and reqs:
            matches = [p for p in prior_stories if p.get("id") not in used_story_ids and set(p.get("requirement_ids", [])) == set(reqs)]
            match = matches[0] if len(matches) == 1 else None
        if match is not None:
            story_id = str(match["id"])
        else:
            story_id, story_high = _next_id("US", used_story_ids, story_high)
        used_story_ids.add(story_id)

        previous_criteria = match.get("acceptance_criteria", []) if match else []
        used_ac: set[str] = set()
        ac_high = max((int(str(c.get("id", "0")).rsplit("AC", 1)[-1])
                       for c in previous_criteria if AC_RE.fullmatch(str(c.get("id", "")))), default=0)
        output_criteria: list[dict[str, str]] = []
        for criterion in criteria:
            signature = "|".join(_normal(criterion[k]) for k in ("given", "when", "then"))
            old = next((c for c in previous_criteria
                        if c.get("id") not in used_ac and "|".join(_normal(str(c.get(k, ""))) for k in ("given", "when", "then")) == signature), None)
            if old is not None:
                ac_id = str(old["id"])
            else:
                ac_high += 1
                ac_id = f"{story_id}-AC{ac_high}"
            used_ac.add(ac_id)
            output_criteria.append({"id": ac_id, **criterion})
        stories.append({
            "id": story_id,
            "epic_id": epic_ref,
            "title": story_title,
            "as_a": as_a,
            "i_want": i_want,
            "so_that": so_that,
            "acceptance_criteria": output_criteria,
            "requirement_ids": reqs,
            "evidence_utterances": evidence,
        })

    if raw_epics and not epics:
        raise DeliveryValidationError("provider response contained no valid epics")
    if raw_stories and not stories:
        raise DeliveryValidationError("provider response contained no valid stories")
    package = {
        "version": 1,
        "revision": int(previous.get("revision", 0)),
        "generated_at": utc_now(),
        "title": _text(response.get("title")) or title,
        "epics": epics,
        "stories": stories,
        "high_water": {"epics": epic_high, "stories": story_high},
    }
    return package, problems


def validate_package(package: dict[str, Any]) -> None:
    """Strict validation for data about to be persisted after user edits."""
    if not isinstance(package, dict) or package.get("version") != 1:
        raise DeliveryValidationError("unsupported delivery package")
    epics = package.get("epics")
    stories = package.get("stories")
    if not isinstance(epics, list) or not isinstance(stories, list):
        raise DeliveryValidationError("epics and stories must be lists")
    epic_ids = [e.get("id") for e in epics if isinstance(e, dict)]
    if len(epic_ids) != len(epics) or len(set(epic_ids)) != len(epic_ids) or not all(EPIC_RE.fullmatch(str(i)) for i in epic_ids):
        raise DeliveryValidationError("epic IDs must be unique E<n> values")
    story_ids = [s.get("id") for s in stories if isinstance(s, dict)]
    if len(story_ids) != len(stories) or len(set(story_ids)) != len(story_ids) or not all(STORY_RE.fullmatch(str(i)) for i in story_ids):
        raise DeliveryValidationError("story IDs must be unique US<n> values")
    for story in stories:
        if story.get("epic_id") not in set(epic_ids):
            raise DeliveryValidationError(f"story {story.get('id')} references an unknown epic")
        for field in ("title", "as_a", "i_want", "so_that"):
            if not _text(story.get(field)):
                raise DeliveryValidationError(f"story {story.get('id')} has an empty {field}")
        criteria = story.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria:
            raise DeliveryValidationError(f"story {story.get('id')} needs acceptance criteria")
        ids = [c.get("id") for c in criteria if isinstance(c, dict)]
        if len(ids) != len(criteria) or len(ids) != len(set(ids)) or not all(AC_RE.fullmatch(str(i)) for i in ids):
            raise DeliveryValidationError(f"story {story.get('id')} has invalid acceptance-criterion IDs")

