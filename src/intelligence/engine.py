"""IntelligenceEngine — incremental analysis loop (docs/ARCHITECTURE.md).

Cadence: a pass runs when >=ENGINE_TRIGGER_NEW_CONTENT_SECONDS of new final
utterance content OR >=ENGINE_TRIGGER_NEW_UTTERANCES new utterances arrived
since the last pass, with at least ENGINE_MIN_SECONDS_BETWEEN_PASSES between
passes. `maybe_analyze` takes an injectable `now` for tests.

Overrides (analyst edits held server-side, re-applied after every pass):
    {"kind": "requirement|decision|open_question|diagram|metric|gap",
     "id": "R2", "action": "pin|dismiss|edit", "text"?: str, "status"?: str}
- dismiss: item removed after every pass; its id goes into a suppression list
  sent to the LLM as "do not re-raise".
- edit: analyst text (and, for open questions, status) wins over LLM output.
- pin: item survives even if the LLM drops it (restored from the previous
  snapshot, which already has earlier overrides applied).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.intelligence import prompts
from src.intelligence.providers import LlmProvider, ProviderError
from src.intelligence.state import (
    QUESTION_STATUSES,
    REQUIREMENT_STATUSES,
    stabilize_state_ids,
    validate_state,
)
from src.sessions.store import SessionStore

CONTEXT_UTTERANCES = 10

# Override "kind" -> SessionState key. Accepts both singular and plural forms.
_KIND_KEYS = {
    "requirement": "requirements", "requirements": "requirements",
    "decision": "decisions", "decisions": "decisions",
    "question": "open_questions", "open_question": "open_questions",
    "open_questions": "open_questions",
    "diagram": "diagrams", "diagrams": "diagrams",
    "metric": "metrics", "metrics": "metrics",
    "gap": "gaps", "gaps": "gaps",
}


@dataclass
class _SessionTrack:
    last_pass_at: float | None = None
    analyzed_through: int = -1  # highest utterance id included in a pass
    id_high_water: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


class IntelligenceEngine:
    def __init__(
        self,
        provider: LlmProvider,
        store: SessionStore,
        *,
        min_gap_seconds: float | None = None,
        content_trigger_seconds: float | None = None,
        utterance_trigger: int | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.min_gap_seconds = (config.ENGINE_MIN_SECONDS_BETWEEN_PASSES
                                if min_gap_seconds is None else min_gap_seconds)
        self.content_trigger_seconds = (config.ENGINE_TRIGGER_NEW_CONTENT_SECONDS
                                        if content_trigger_seconds is None
                                        else content_trigger_seconds)
        self.utterance_trigger = (config.ENGINE_TRIGGER_NEW_UTTERANCES
                                  if utterance_trigger is None else utterance_trigger)
        self._tracks: dict[str, _SessionTrack] = {}

    def _track(self, session_id: str) -> _SessionTrack:
        track = self._tracks.get(session_id)
        if track is None:
            track = _SessionTrack(
                analyzed_through=self.store.load_analysis_watermark(session_id),
                id_high_water=self.store.load_id_high_water(session_id),
            )
            self._tracks[session_id] = track
        return track

    # -- cadence ---------------------------------------------------------------

    def maybe_analyze(self, session_id: str,
                      now: float | None = None) -> dict[str, Any] | None:
        """Run a pass if cadence thresholds are met; return the new state or None."""
        now = time.monotonic() if now is None else now
        track = self._track(session_id)
        if (track.last_pass_at is not None
                and now - track.last_pass_at < self.min_gap_seconds):
            return None
        new = [u for u in self.store.load_utterances(session_id)
               if u.id > track.analyzed_through]
        if not new:
            return None
        new_seconds = sum(max(0.0, u.t1 - u.t0) for u in new)
        if (len(new) < self.utterance_trigger
                and new_seconds < self.content_trigger_seconds):
            return None
        return self.analyze(session_id, now=now)

    # -- analysis pass ------------------------------------------------------------

    def analyze(self, session_id: str,
                now: float | None = None) -> dict[str, Any] | None:
        """One full LLM pass. Returns the persisted state, or None on ProviderError.

        Also used for on-demand (POST /analyze) and final-on-stop passes, which
        bypass the cadence check.
        """
        now = time.monotonic() if now is None else now
        track = self._track(session_id)

        utterances = self.store.load_utterances(session_id)
        previous_state, rev = self.store.load_state(session_id)
        overrides = self.store.load_overrides(session_id)

        new = [u for u in utterances if u.id > track.analyzed_through]
        context = [u for u in utterances
                   if u.id <= track.analyzed_through][-CONTEXT_UTTERANCES:]
        suppressed = _suppressed_descriptions(overrides, previous_state)

        system, user = prompts.build_analysis_prompt(
            previous_state, new, context, suppressed)
        try:
            raw = self.provider.complete_json(system, user, prompts.STATE_SCHEMA_HINT)
        except ProviderError:
            return None  # never crash the session; next cadence tick retries

        state, problems = validate_state(raw)
        problems.extend(stabilize_state_ids(
            state, previous_state, high_water=track.id_high_water))
        _add_dropped_diagram_gaps(state, previous_state, problems)
        _apply_overrides(state, previous_state, overrides)

        rev += 1
        analyzed_through = max((u.id for u in utterances),
                               default=track.analyzed_through)
        self.store.snapshot_state(session_id, state, rev,
                                  analyzed_through=analyzed_through,
                                  id_high_water=track.id_high_water)
        track.last_pass_at = now
        track.analyzed_through = analyzed_through
        track.problems = problems
        return state


# -- override application (module-level: reused by server on manual override) --


def _suppressed_descriptions(overrides: list[dict[str, Any]],
                             previous_state: dict[str, Any]) -> list[str]:
    """'do not re-raise' lines for every dismissed item, with last-known text."""
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for o in overrides:
        if o.get("action") != "dismiss":
            continue
        key = _KIND_KEYS.get(str(o.get("kind", "")).lower())
        item_id = o.get("id")
        if key is None or not isinstance(item_id, str) or (key, item_id) in seen:
            continue
        seen.add((key, item_id))
        text = next((i.get("text") or i.get("title", "")
                     for i in previous_state.get(key, []) if i.get("id") == item_id), "")
        out.append(f"{key}/{item_id}: {text}" if text else f"{key}/{item_id}")
    return out


def _apply_overrides(state: dict[str, Any], previous_state: dict[str, Any],
                     overrides: list[dict[str, Any]]) -> None:
    """Re-apply analyst overrides in chronological order (mutates `state`)."""
    for o in overrides:
        key = _KIND_KEYS.get(str(o.get("kind", "")).lower())
        item_id = o.get("id")
        action = o.get("action")
        if key is None or not isinstance(item_id, str):
            continue
        items: list[dict[str, Any]] = state[key]
        if action == "dismiss":
            state[key] = [i for i in items if i.get("id") != item_id]
        elif action == "edit":
            if not any(i.get("id") == item_id for i in items):
                kept = next((i for i in previous_state.get(key, [])
                             if i.get("id") == item_id), None)
                if kept is not None:
                    items.append(dict(kept))
            for item in items:
                if item.get("id") != item_id:
                    continue
                if isinstance(o.get("text"), str):
                    # Diagrams/metrics have "title" where others have "text".
                    item["title" if "text" not in item else "text"] = o["text"]
                status = o.get("status")
                allowed = (REQUIREMENT_STATUSES if key == "requirements"
                           else QUESTION_STATUSES if key == "open_questions"
                           else set())
                if isinstance(status, str) and status in allowed:
                    item["status"] = status
        elif action == "pin":
            if not any(i.get("id") == item_id for i in items):
                kept = next((i for i in previous_state.get(key, [])
                             if i.get("id") == item_id), None)
                if kept is not None:
                    items.append(dict(kept))


def _add_dropped_diagram_gaps(state: dict[str, Any], previous_state: dict[str, Any],
                              problems: list[str]) -> None:
    """TS-005-02: an invalid Mermaid diagram becomes a gap note, never a broken
    client render. Gap ids continue the existing X-sequence."""
    diagram_problems = [p for p in problems if p.startswith("diagrams/")]
    if not diagram_problems:
        return
    known_gaps = list(previous_state.get("gaps", [])) + state["gaps"]
    next_n = 1 + max(
        (int(m.group(1)) for i in known_gaps
         if (m := re.fullmatch(r"X(\d+)", str(i.get("id", ""))))),
        default=0,
    )
    for problem in diagram_problems:
        state["gaps"].append({
            "id": f"X{next_n}",
            "text": f"A generated process diagram was dropped as invalid ({problem}). "
                    "The process description may need to be re-elicited.",
            "category": "edge_cases",
            "evidence_utterances": [],
        })
        next_n += 1
