"""Crash-safe per-session persistence for delivery artifacts and Jira mappings."""
from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

from src.delivery.models import validate_package
from src.sessions.store import SessionStore


class DeliveryNotFound(KeyError):
    """Raised when stories have not been generated for a session."""


class DeliveryRepository:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def _path(self, session_id: str) -> Path:
        return self.store.session_dir(session_id) / "delivery.json"

    def _jira_path(self, session_id: str) -> Path:
        return self.store.session_dir(session_id) / "jira-mapping.json"

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).is_file()

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.is_file():
            raise DeliveryNotFound(f"no delivery package for session {session_id!r}")
        with path.open("r", encoding="utf-8") as fh:
            package = json.load(fh)
        validate_package(package)
        return package

    def save(self, session_id: str, package: dict[str, Any]) -> dict[str, Any]:
        package = copy.deepcopy(package)
        validate_package(package)
        previous_revision = 0
        if self._path(session_id).is_file():
            try:
                previous_revision = int(self.load(session_id).get("revision", 0))
            except (DeliveryNotFound, ValueError, json.JSONDecodeError):
                previous_revision = 0
        package["revision"] = previous_revision + 1
        self._atomic_json(self._path(session_id), package)
        return package

    def load_jira_mapping(self, session_id: str) -> dict[str, Any]:
        path = self._jira_path(session_id)
        if not path.is_file():
            return {"version": 1, "issues": {}}
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict) or not isinstance(doc.get("issues"), dict):
            return {"version": 1, "issues": {}}
        return doc

    def save_jira_mapping(self, session_id: str, mapping: dict[str, Any]) -> None:
        if not isinstance(mapping, dict) or not isinstance(mapping.get("issues"), dict):
            raise ValueError("invalid Jira mapping")
        self._atomic_json(self._jira_path(session_id), mapping)

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

