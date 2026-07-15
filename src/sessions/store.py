"""Local session persistence (docs/ARCHITECTURE.md — Session store).

Layout, all under data_dir/sessions/<session_id>/:
    meta.json          {"id", "title", "started"}          (written once)
    utterances.jsonl   one Utterance JSON per line          (append, flushed)
    overrides.jsonl    one override dict per line           (append, flushed)
    state.json         {"rev": int, "state": SessionState}  (atomic replace)

Appends flush per line so a crash loses at most the line being written;
state snapshots are written to a temp file and os.replace'd so readers never
see a torn file (TS-011-01).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.intelligence.state import Utterance, empty_state


class SessionStore:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # -- session lifecycle -------------------------------------------------

    def create_session(self, title: str = "") -> str:
        with self._lock:
            while True:
                sid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
                path = self.sessions_dir / sid
                try:
                    path.mkdir(parents=False)
                except FileExistsError:
                    continue
                break
            meta = {
                "id": sid,
                "title": title if isinstance(title, str) else str(title),
                "started": datetime.now(timezone.utc).isoformat(),
            }
            self._atomic_write_json(path / "meta.json", meta)
        return sid

    def session_dir(self, session_id: str) -> Path:
        # Session ids come from URLs — refuse anything path-like.
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?", session_id
        ) or ".." in session_id:
            raise ValueError(f"invalid session id {session_id!r}")
        path = self.sessions_dir / session_id
        if not path.is_dir():
            raise KeyError(f"unknown session {session_id!r}")
        return path

    # -- utterances ----------------------------------------------------------

    def append_utterance(self, session_id: str, utterance: Utterance) -> None:
        if not isinstance(utterance, Utterance):
            raise TypeError("utterance must be an Utterance")
        with self._lock:
            self._append_jsonl(self.session_dir(session_id) / "utterances.jsonl",
                               utterance.to_json())

    def load_utterances(self, session_id: str) -> list[Utterance]:
        return [Utterance.from_json(d) for d in
                self._read_jsonl(self.session_dir(session_id) / "utterances.jsonl")]

    # -- state snapshots -----------------------------------------------------

    def snapshot_state(self, session_id: str, state: dict[str, Any], rev: int,
                       analyzed_through: int | None = None,
                       id_high_water: dict[str, int] | None = None) -> None:
        if not isinstance(state, dict):
            raise TypeError("state must be an object")
        if isinstance(rev, bool) or not isinstance(rev, int) or rev < 0:
            raise ValueError("rev must be a non-negative integer")
        with self._lock:
            path = self.session_dir(session_id) / "state.json"
            existing: dict[str, Any] = {}
            if path.is_file():
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        existing = json.load(fh)
                except (OSError, json.JSONDecodeError):
                    existing = {}
            doc: dict[str, Any] = {"rev": rev, "state": state}
            watermark = (analyzed_through if analyzed_through is not None
                         else existing.get("analyzed_through"))
            counters = (id_high_water if id_high_water is not None
                        else existing.get("id_high_water"))
            if isinstance(watermark, int) and not isinstance(watermark, bool):
                doc["analyzed_through"] = watermark
            if isinstance(counters, dict):
                doc["id_high_water"] = counters
            self._atomic_write_json(path, doc)

    def load_state(self, session_id: str) -> tuple[dict[str, Any], int]:
        """Return (state, rev); (empty_state(), 0) when no snapshot exists yet."""
        path = self.session_dir(session_id) / "state.json"
        if not path.is_file():
            return empty_state(), 0
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc["state"], int(doc["rev"])

    def load_analysis_watermark(self, session_id: str) -> int:
        """Highest utterance included in the latest state, or -1 for old snapshots."""
        path = self.session_dir(session_id) / "state.json"
        if not path.is_file():
            return -1
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        value = doc.get("analyzed_through", -1)
        return value if isinstance(value, int) and not isinstance(value, bool) else -1

    def load_id_high_water(self, session_id: str) -> dict[str, int]:
        """Persisted next-ID guards used to avoid reusing retired item IDs."""
        path = self.session_dir(session_id) / "state.json"
        if not path.is_file():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            value = json.load(fh).get("id_high_water", {})
        if not isinstance(value, dict):
            return {}
        return {str(key): number for key, number in value.items()
                if isinstance(number, int) and not isinstance(number, bool) and number >= 0}

    # -- overrides -------------------------------------------------------------

    def append_override(self, session_id: str, override: dict[str, Any]) -> None:
        if not isinstance(override, dict):
            raise TypeError("override must be an object")
        with self._lock:
            self._append_jsonl(self.session_dir(session_id) / "overrides.jsonl",
                               dict(override))

    def load_overrides(self, session_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl(self.session_dir(session_id) / "overrides.jsonl")

    # -- listing / loading -------------------------------------------------------

    def list_sessions(self) -> list[dict[str, Any]]:
        """Summaries (id, title, started, duration, utterance_count), newest first."""
        out: list[dict[str, Any]] = []
        for path in sorted(self.sessions_dir.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            meta_path = path / "meta.json"
            if not meta_path.is_file():
                continue
            with meta_path.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
            utterances = self._read_jsonl(path / "utterances.jsonl")
            duration = max((u.get("t1", 0.0) for u in utterances), default=0.0)
            title = meta.get("title", "")
            if not title:
                state_path = path / "state.json"
                if state_path.is_file():
                    try:
                        with state_path.open("r", encoding="utf-8") as fh:
                            title = json.load(fh).get("state", {}).get("title", "")
                    except (OSError, json.JSONDecodeError, AttributeError):
                        title = ""
            out.append({
                "id": meta["id"],
                "title": title,
                "started": meta.get("started", ""),
                "duration": duration,
                "utterance_count": len(utterances),
            })
        return out

    def load_session(self, session_id: str) -> dict[str, Any]:
        """Full session: meta, utterances, latest state+rev, overrides."""
        path = self.session_dir(session_id)
        with (path / "meta.json").open("r", encoding="utf-8") as fh:
            meta = json.load(fh)
        state, rev = self.load_state(session_id)
        return {
            "id": session_id,
            "meta": meta,
            "utterances": self.load_utterances(session_id),
            "state": state,
            "rev": rev,
            "overrides": self.load_overrides(session_id),
        }

    # -- low-level file helpers -----------------------------------------------------

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        with path.open("a+b") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    fh.seek(0, os.SEEK_END)
                    fh.write(b"\n")
            fh.seek(0, os.SEEK_END)
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn final line after a crash — skip, keep the rest
        return out

    @staticmethod
    def _atomic_write_json(path: Path, doc: dict[str, Any]) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
