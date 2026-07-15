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


_NODE = r'[A-Za-z][A-Za-z0-9_]*(?:\["[^"\r\n]*"\]|\{"[^"\r\n]*"\})?'
_MERMAID_LINE = re.compile(rf"(?:{_NODE})(?:\s*-->\s*(?:\|\"[^\"\r\n]*\"\|\s*)?(?:{_NODE}))?")
_UNSAFE_MERMAID = re.compile(r"\b(?:subgraph|style|classDef|class|click|linkStyle)\b|%%|;", re.I)
_FORBIDDEN_MERMAID = re.compile(
    r"\b(?:subgraph|style|classDef|class|click|linkStyle|href|javascript)\b"
    r"|%%|<\s*/?\s*[A-Za-z]|`",
    re.I,
)
_PLAIN_EDGE_LABEL = re.compile(r"(?<=-->)\s*\|([^|\"\r\n]+)\|\s*")
_PLAIN_NODE_LABEL = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_]*)\s*([\[{(])"
    r"([A-Za-z0-9 ,.?!&/()'_-]+)([\]})])"
)
_QUOTED_ROUND_NODE = re.compile(r'\b([A-Za-z][A-Za-z0-9_]*)\s*\("([^"\r\n]*)"\)')
_NODE_ONLY = re.compile(_NODE)


def valid_mermaid(source: str) -> bool:
    """Accept only the deliberately small, safe Mermaid subset in the contract."""
    lines = [line.strip() for line in source.strip().splitlines() if line.strip()]
    if not lines or lines[0] != "flowchart TD":
        return False
    return bool(len(lines) > 1 and all(
        not _UNSAFE_MERMAID.search(line) and _MERMAID_LINE.fullmatch(line)
        for line in lines[1:]
    ))


def normalize_mermaid(source: str) -> str | None:
    """Repair harmless provider variations, then enforce the safe subset.

    Local models commonly omit quotes around edge labels (``-->|Yes|``), even
    when the prompt requests them. Quoting those labels does not broaden the
    accepted Mermaid language; the normalized result must still pass the same
    deliberately small allow-list used by :func:`valid_mermaid`.
    """
    if not isinstance(source, str) or _FORBIDDEN_MERMAID.search(source):
        return None
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        lines = lines[1:] if lines else []
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    normalized = re.sub(
        r"\A(?:graph|flowchart)\s+(?:TD|TB|BT|LR|RL)\b",
        "flowchart TD",
        normalized,
        flags=re.I,
    )
    # A semicolon is accepted only as a statement separator during repair. Any
    # forbidden statement keyword was rejected above, and the rebuilt result
    # must still pass the strict line-by-line allow-list.
    normalized = "\n".join(part.strip() for part in normalized.split(";") if part.strip())
    normalized = _QUOTED_ROUND_NODE.sub(
        lambda match: f'{match.group(1)}["{match.group(2)}"]', normalized)
    normalized = _PLAIN_NODE_LABEL.sub(
        lambda match: (
            f'{match.group(1)}{{"{match.group(3).strip()}"}}'
            if match.group(2) == "{"
            else f'{match.group(1)}["{match.group(3).strip()}"]'
        ),
        normalized,
    )
    normalized = _PLAIN_EDGE_LABEL.sub(
        lambda match: f' |"{match.group(1).strip()}"| ', normalized)
    # Expand compact chains (A --> B --> C) into the same strict one-edge-per-
    # line representation. Every token is checked against the node allow-list
    # before it is copied into the rebuilt source.
    lines = [line for line in normalized.splitlines() if line.strip()]
    if not lines:
        return None
    expanded = [lines[0].strip()]
    for original_line in lines[1:]:
        line = original_line.strip()
        parts = [part.strip() for part in line.split("-->")]
        if len(parts) <= 2:
            expanded.append(original_line.rstrip())
            continue
        left = parts[0]
        if not _NODE_ONLY.fullmatch(left):
            return None
        for part in parts[1:]:
            match = re.fullmatch(r'(?:\|("[^"\r\n]*")\|\s*)?(.+)', part)
            if match is None or not _NODE_ONLY.fullmatch(match.group(2).strip()):
                return None
            label = f" |{match.group(1)}|" if match.group(1) else ""
            right = match.group(2).strip()
            expanded.append(f"{left} -->{label} {right}")
            left = right
    # Keep a usable safe diagram when a provider appends one malformed edge to
    # an otherwise valid flow. Forbidden constructs already rejected the whole
    # source above; here we retain only lines that independently match the
    # allow-list. A diagram with no valid edge is still rejected.
    safe_lines = [
        line for line in expanded[1:]
        if _MERMAID_LINE.fullmatch(line.strip())
    ]
    normalized = "\n".join([expanded[0], *safe_lines])
    return normalized if valid_mermaid(normalized) else None


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
            elif key == "diagrams":
                normalized_mermaid = normalize_mermaid(item["mermaid"])
                if normalized_mermaid is None:
                    problems.append(f"diagrams/{item_id}: invalid or unsafe Mermaid; dropped")
                    continue
                item["mermaid"] = normalized_mermaid

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
