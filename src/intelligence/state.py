"""Validated session-state contract shared by the engine, store, and UI."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Utterance:
    """One finalized speech segment; times are session-relative seconds."""

    id: int
    t0: float
    t1: float
    text: str

    def __post_init__(self) -> None:
        if isinstance(self.id, bool) or not isinstance(self.id, int) or self.id < 0:
            raise ValueError("utterance id must be a non-negative integer")
        if not _finite_number(self.t0) or not _finite_number(self.t1):
            raise ValueError("utterance times must be finite numbers")
        if self.t0 < 0 or self.t1 < self.t0:
            raise ValueError("utterance times must satisfy 0 <= t0 <= t1")
        if not isinstance(self.text, str):
            raise TypeError("utterance text must be a string")

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(d: dict[str, Any]) -> "Utterance":
        if not isinstance(d, dict):
            raise TypeError("utterance record must be an object")
        return Utterance(id=d["id"], t0=d["t0"], t1=d["t1"], text=d["text"])


def _finite_number(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)))


def mmss(seconds: float) -> str:
    """Format session-relative seconds as ``mm:ss``."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


REQUIREMENT_STATUSES = {"captured", "clarifying", "confirmed"}
QUESTION_STATUSES = {"suggested", "asked", "answered", "parked"}
QUESTION_CATEGORIES = {"actors", "data", "volumes", "exceptions", "nfr", "acceptance", "general"}
GAP_CATEGORIES = {"actors", "definitions", "nfr", "edge_cases", "conflict"}
DIAGRAM_KINDS = {"flowchart", "process"}
METRIC_KINDS = {"bar", "pie"}

STATE_LIST_KEYS = (
    "requirements", "decisions", "open_questions", "diagrams", "metrics", "gaps",
)
ID_PREFIXES = {
    "requirements": "R", "decisions": "D", "open_questions": "Q",
    "diagrams": "G", "metrics": "M", "gaps": "X",
}


def empty_state() -> dict[str, Any]:
    return {
        "title": "", "summary": [], "requirements": [], "decisions": [],
        "open_questions": [], "diagrams": [], "metrics": [], "gaps": [],
    }


def _evidence(value: Any, key: str, item_id: str, problems: list[str]) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{key}/{item_id}: 'evidence_utterances' must be a list; reset")
        return []
    result: list[int] = []
    for utterance_id in value:
        if (isinstance(utterance_id, bool) or not isinstance(utterance_id, int)
                or utterance_id < 0):
            problems.append(f"{key}/{item_id}: invalid evidence utterance {utterance_id!r} dropped")
        elif utterance_id not in result:
            result.append(utterance_id)
    return result


_NODE = r'[A-Za-z][A-Za-z0-9]*(?:\["[^"\r\n]*"\]|\{"[^"\r\n]*"\})?'
_MERMAID_LINE = re.compile(rf"(?:{_NODE})(?:\s*-->\s*(?:\|\"[^\"\r\n]*\"\|\s*)?(?:{_NODE}))?")
_UNSAFE_MERMAID = re.compile(r"\b(?:subgraph|style|classDef|class|click|linkStyle)\b|%%|;", re.I)


def valid_mermaid(source: str) -> bool:
    """Accept only the deliberately small, safe Mermaid subset in the contract."""
    lines = [line.strip() for line in source.strip().splitlines() if line.strip()]
    if not lines or lines[0] != "flowchart TD":
        return False
    return bool(len(lines) > 1 and all(
        not _UNSAFE_MERMAID.search(line) and _MERMAID_LINE.fullmatch(line)
        for line in lines[1:]
    ))


def validate_state(state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Sanitize an untrusted LLM response into a complete SessionState.

    Invalid items are dropped and described in ``problems``. This function is
    intentionally non-throwing because provider output must not break a live
    session.
    """
    problems: list[str] = []
    clean = empty_state()
    if not isinstance(state, dict):
        return clean, ["state is not an object"]

    if isinstance(state.get("title"), str):
        clean["title"] = state["title"].strip()
    elif "title" in state:
        problems.append("title: expected string; reset")
    summary = state.get("summary", [])
    if isinstance(summary, list):
        clean["summary"] = [s.strip() for s in summary if isinstance(s, str) and s.strip()]
    else:
        problems.append("summary: expected list; reset")

    specs: dict[str, tuple[dict[str, type], dict[str, set[str]]]] = {
        "requirements": ({"id": str, "text": str, "status": str}, {"status": REQUIREMENT_STATUSES}),
        "decisions": ({"id": str, "text": str}, {}),
        "open_questions": ({"id": str, "text": str, "status": str, "category": str},
                           {"status": QUESTION_STATUSES, "category": QUESTION_CATEGORIES}),
        "diagrams": ({"id": str, "kind": str, "title": str, "mermaid": str}, {"kind": DIAGRAM_KINDS}),
        "metrics": ({"id": str, "kind": str, "title": str, "labels": list, "values": list}, {"kind": METRIC_KINDS}),
        "gaps": ({"id": str, "text": str, "category": str}, {"category": GAP_CATEGORIES}),
    }

    for key, (required, enums) in specs.items():
        source = state.get(key, [])
        if not isinstance(source, list):
            problems.append(f"{key}: expected list; reset")
            continue
        prefix = ID_PREFIXES[key]
        seen_ids: set[str] = set()
        for original in source:
            if not isinstance(original, dict):
                problems.append(f"{key}: non-object item dropped")
                continue
            item = dict(original)
            item_id = item.get("id", "?")
            bad_field = next((name for name, kind in required.items()
                              if not isinstance(item.get(name), kind)), None)
            if bad_field:
                problems.append(f"{key}/{item_id}: bad or missing '{bad_field}'")
                continue
            if not re.fullmatch(rf"{prefix}[1-9]\d*", item["id"]):
                problems.append(f"{key}/{item_id}: invalid id; item dropped")
                continue
            if item["id"] in seen_ids:
                problems.append(f"{key}/{item_id}: duplicate id; later item dropped")
                continue
            bad_enum = next((name for name, allowed in enums.items()
                             if item.get(name) not in allowed), None)
            if bad_enum:
                problems.append(f"{key}/{item_id}: invalid '{bad_enum}'")
                continue
            if "text" in item and not item["text"].strip():
                problems.append(f"{key}/{item_id}: empty text; item dropped")
                continue
            if "title" in item and not item["title"].strip():
                problems.append(f"{key}/{item_id}: empty title; item dropped")
                continue

            if key == "open_questions":
                requirement_id = item.get("requirement_id")
                if requirement_id is not None and not (
                    isinstance(requirement_id, str) and re.fullmatch(r"R[1-9]\d*", requirement_id)
                ):
                    problems.append(f"{key}/{item_id}: invalid requirement_id removed")
                    item.pop("requirement_id", None)
            else:
                item["evidence_utterances"] = _evidence(
                    item.get("evidence_utterances"), key, item["id"], problems)
            if key == "metrics":
                if (not all(isinstance(label, str) and label.strip() for label in item["labels"])
                        or not all(_finite_number(value) for value in item["values"])
                        or len(item["labels"]) != len(item["values"])
                        or not item["labels"]):
                    problems.append(f"metrics/{item_id}: invalid labels/values; item dropped")
                    continue
            elif key == "diagrams" and not valid_mermaid(item["mermaid"]):
                problems.append(f"diagrams/{item_id}: invalid or unsafe Mermaid; dropped")
                continue

            allowed_fields = set(required)
            if key != "open_questions":
                allowed_fields.add("evidence_utterances")
            if key == "open_questions":
                allowed_fields.add("requirement_id")
            clean[key].append({name: item[name] for name in allowed_fields if name in item})
            seen_ids.add(item["id"])

    valid_requirements = {item["id"] for item in clean["requirements"]}
    for question in clean["open_questions"]:
        if question.get("requirement_id") not in valid_requirements:
            if "requirement_id" in question:
                problems.append(
                    f"open_questions/{question['id']}: unknown requirement_id removed")
                question.pop("requirement_id", None)

    return clean, problems


def stabilize_state_ids(state: dict[str, Any], previous: dict[str, Any],
                        high_water: dict[str, int] | None = None) -> list[str]:
    """Repair provider ID drift while preserving genuine new-item ordering.

    Existing IDs win. If a provider renumbers an unchanged item, exact
    normalized text/title or overlapping evidence maps it back to the prior ID.
    Remaining genuinely new items receive the next sequential ID.
    """
    repairs: list[str] = []
    requirement_id_map: dict[str, str] = {}
    for key in STATE_LIST_KEYS:
        prefix = ID_PREFIXES[key]
        prior = previous.get(key, []) if isinstance(previous.get(key, []), list) else []
        current = state[key]
        prior_by_id = {i.get("id"): i for i in prior if isinstance(i, dict)}
        used: set[str] = set()

        def normalized(item: dict[str, Any]) -> str:
            value = str(item.get("text", item.get("title", ""))).casefold()
            return re.sub(r"\W+", " ", value).strip()

        # Keep IDs that are already valid carry-overs.
        for item in current:
            if item["id"] in prior_by_id and item["id"] not in used:
                used.add(item["id"])

        for item in current:
            old_id = item["id"]
            if old_id in used and old_id in prior_by_id:
                continue
            available = [p for p in prior if p.get("id") not in used]
            match = next((p for p in available if normalized(p) == normalized(item)), None)
            if match is None:
                evidence = set(item.get("evidence_utterances", []))
                candidates = [p for p in available
                              if evidence and evidence.intersection(p.get("evidence_utterances", []))]
                if len(candidates) == 1:
                    match = candidates[0]
            if match is not None:
                item["id"] = match["id"]
                used.add(item["id"])
                repairs.append(f"{key}: repaired {old_id} to stable {item['id']}")
                if key == "requirements":
                    requirement_id_map[old_id] = item["id"]
            else:
                item["id"] = ""  # assigned below as a genuinely new item

        highest = max(
            max((int(i["id"][1:]) for i in prior
                 if isinstance(i, dict) and re.fullmatch(
                     rf"{prefix}[1-9]\d*", str(i.get("id", "")))), default=0),
            (high_water or {}).get(key, 0),
        )
        for item in current:
            if item["id"]:
                continue
            highest += 1
            while f"{prefix}{highest}" in used:
                highest += 1
            item["id"] = f"{prefix}{highest}"
            used.add(item["id"])
        if high_water is not None:
            high_water[key] = max(highest, high_water.get(key, 0))
        # Ensure question links follow repaired requirement IDs.
        if key == "requirements":
            state_ids = {item["id"] for item in current}
            for question in state["open_questions"]:
                ref = question.get("requirement_id")
                if ref in requirement_id_map:
                    question["requirement_id"] = requirement_id_map[ref]
                if question.get("requirement_id") not in state_ids:
                    question.pop("requirement_id", None)
    return repairs
