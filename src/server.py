"""ReqPilot localhost REST/WebSocket server."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import (
    Body,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src import config
from src.audio.engine import AsrEngine
from src.delivery import (
    DeliveryNotFound,
    DeliveryRepository,
    DeliveryValidationError,
    JiraCloudClient,
    JiraConfig,
    JiraError,
    JiraSyncService,
    StoryService,
    export_brd_docx,
)
from src.importers import MAX_IMPORT_BYTES, TranscriptImportError, import_transcript
from src.intelligence.brd import generate_brd
from src.intelligence.engine import IntelligenceEngine, _apply_overrides
from src.intelligence.providers import LlmProvider, ProviderError, get_provider
from src.intelligence.state import Utterance
from src.sessions.store import SessionStore


def create_app(
    *,
    store: SessionStore | None = None,
    provider: LlmProvider | None = None,
    asr_factory: Callable[..., AsrEngine] | None = None,
    jira_client: JiraCloudClient | None = None,
) -> FastAPI:
    app = FastAPI(title="ReqPilot", version="0.1.0")
    app.state.store = store or SessionStore(config.DATA_DIR)
    app.state.provider = provider or get_provider()
    app.state.intelligence = IntelligenceEngine(app.state.provider, app.state.store)
    app.state.asr_factory = asr_factory or AsrEngine
    app.state.delivery_repo = DeliveryRepository(app.state.store)
    app.state.story_service = StoryService(
        app.state.store, app.state.provider, app.state.delivery_repo
    )
    app.state.jira_client = jira_client

    def known_session(session_id: str) -> None:
        try:
            app.state.store.session_dir(session_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def delivery_call(call: Callable[[], Any]) -> Any:
        """Translate service errors into stable API responses without secrets."""
        try:
            return call()
        except DeliveryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (DeliveryValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except JiraError as exc:
            raise HTTPException(status_code=502, detail={
                "message": str(exc), "jira_status": exc.status_code,
                "details": exc.details,
            }) from exc

    def jira_configuration(project_key: str = "") -> JiraConfig:
        injected = app.state.jira_client
        if injected is not None:
            current = injected.config
            chosen = project_key.strip().upper() or current.project_key
            if chosen == current.project_key:
                return current
            return JiraConfig(
                base_url=current.base_url,
                email=current.email,
                api_token=current.api_token,
                project_key=chosen,
                epic_issue_type=current.epic_issue_type,
                story_issue_type=current.story_issue_type,
            )
        values = {
            "base_url": os.environ.get("JIRA_BASE_URL", "").strip(),
            "email": os.environ.get("JIRA_EMAIL", "").strip(),
            "api_token": os.environ.get("JIRA_API_TOKEN", "").strip(),
            "project_key": project_key.strip().upper()
                           or os.environ.get("JIRA_PROJECT_KEY", "").strip().upper(),
        }
        if not all(values.values()):
            raise HTTPException(
                status_code=503,
                detail="Jira is not configured; set JIRA_BASE_URL, JIRA_EMAIL, "
                       "JIRA_API_TOKEN, and JIRA_PROJECT_KEY",
            )
        return JiraConfig(**values)

    def jira_for(project_key: str = "") -> tuple[JiraCloudClient, bool]:
        configuration = jira_configuration(project_key)
        injected = app.state.jira_client
        if injected is not None and configuration is injected.config:
            return injected, False
        return JiraCloudClient(configuration), True

    @app.post("/api/session")
    def create_session(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, str]:
        title = payload.get("title", "") if isinstance(payload, dict) else ""
        return {"id": app.state.store.create_session(str(title))}

    @app.post("/api/session/import")
    async def import_session(
        file: UploadFile | None = File(default=None),
        text: str | None = Form(default=None),
        filename: str | None = Form(default=None),
        title: str = Form(default=""),
    ) -> dict[str, Any]:
        """Create, persist, and fully analyze one imported transcript."""
        if (file is None) == (text is None):
            raise HTTPException(
                status_code=400,
                detail="provide exactly one transcript source: file or text",
            )

        try:
            if file is not None:
                source_name = filename or file.filename or ""
                try:
                    content = await file.read(MAX_IMPORT_BYTES + 1)
                finally:
                    await file.close()
            else:
                source_name = filename or "pasted.txt"
                content = text or ""
            parsed = import_transcript(content, source_name)
        except TranscriptImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        clean_title = title.strip()
        if len(clean_title) > 200:
            raise HTTPException(status_code=422, detail="title must be at most 200 characters")
        if not clean_title:
            clean_title = Path(parsed.filename).stem[:200]

        # Parsing happens first: malformed input never leaves an empty session behind.
        session_id = app.state.store.create_session(clean_title)
        for utterance in parsed.utterances:
            app.state.store.append_utterance(session_id, utterance)

        state = await asyncio.to_thread(app.state.intelligence.analyze, session_id)
        if state is None:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "transcript was imported but intelligence analysis failed",
                    "session_id": session_id,
                },
            )
        _state, rev = app.state.store.load_state(session_id)
        return {
            "session": {"id": session_id, "title": clean_title,
                        "filename": parsed.filename, "format": parsed.format},
            "state": state,
            "rev": rev,
            "count": len(parsed.utterances),
        }

    @app.get("/api/session/{session_id}/state")
    def get_state(session_id: str) -> dict[str, Any]:
        known_session(session_id)
        state, _rev = app.state.store.load_state(session_id)
        return state

    @app.get("/api/session/{session_id}/transcript")
    def get_transcript(session_id: str) -> dict[str, Any]:
        known_session(session_id)
        utterances = [item.to_json() for item in app.state.store.load_utterances(session_id)]
        return {"session": session_id, "count": len(utterances), "utterances": utterances}

    @app.post("/api/session/{session_id}/analyze")
    def analyze(session_id: str) -> dict[str, Any]:
        known_session(session_id)
        state = app.state.intelligence.analyze(session_id)
        if state is None:
            raise HTTPException(status_code=502, detail="intelligence provider did not return valid state")
        _state, rev = app.state.store.load_state(session_id)
        return {"state": state, "rev": rev}

    @app.post("/api/session/{session_id}/brd")
    def brd(session_id: str) -> dict[str, str]:
        known_session(session_id)
        return {"markdown": generate_brd(session_id, app.state.store, app.state.provider)}

    @app.get("/api/session/{session_id}/brd.docx")
    @app.post("/api/session/{session_id}/brd.docx")
    async def brd_docx(session_id: str) -> FileResponse:
        known_session(session_id)
        output = app.state.store.session_dir(session_id) / "exports" / "brd.docx"
        path = await asyncio.to_thread(
            delivery_call,
            lambda: export_brd_docx(
                session_id, app.state.store, app.state.provider, output
            ),
        )
        return FileResponse(
            path,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            filename=f"{session_id}-brd.docx",
        )

    @app.get("/api/session/{session_id}/stories")
    def get_stories(session_id: str) -> dict[str, Any]:
        known_session(session_id)
        try:
            return app.state.story_service.get(session_id)
        except DeliveryNotFound:
            # An empty backlog is a valid pre-generation workspace state.
            return {"version": 1, "revision": 0, "title": "",
                    "epics": [], "stories": []}

    @app.post("/api/session/{session_id}/stories")
    @app.post("/api/session/{session_id}/stories/generate")
    async def generate_stories(session_id: str) -> dict[str, Any]:
        known_session(session_id)
        return await asyncio.to_thread(
            delivery_call, lambda: app.state.story_service.generate(session_id)
        )

    @app.patch("/api/session/{session_id}/epics/{epic_id}")
    def update_epic(session_id: str, epic_id: str,
                    payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        known_session(session_id)
        return delivery_call(
            lambda: app.state.story_service.update_epic(session_id, epic_id, payload)
        )

    @app.delete("/api/session/{session_id}/epics/{epic_id}")
    def delete_epic(session_id: str, epic_id: str) -> dict[str, Any]:
        known_session(session_id)
        return delivery_call(
            lambda: app.state.story_service.delete_epic(session_id, epic_id)
        )

    @app.patch("/api/session/{session_id}/stories/{story_id}")
    def update_story(session_id: str, story_id: str,
                     payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        known_session(session_id)
        return delivery_call(
            lambda: app.state.story_service.update_story(session_id, story_id, payload)
        )

    @app.delete("/api/session/{session_id}/stories/{story_id}")
    def delete_story(session_id: str, story_id: str) -> dict[str, Any]:
        known_session(session_id)
        return delivery_call(
            lambda: app.state.story_service.delete_story(session_id, story_id)
        )

    @app.post("/api/session/{session_id}/stories/merge")
    def merge_stories(session_id: str,
                      payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        known_session(session_id)
        target_id = payload.get("target_id")
        source_ids = payload.get("source_ids")
        if not isinstance(target_id, str) or not isinstance(source_ids, list):
            raise HTTPException(
                status_code=422, detail="target_id and source_ids are required"
            )
        return delivery_call(
            lambda: app.state.story_service.merge_stories(
                session_id, target_id, source_ids
            )
        )

    @app.post("/api/session/{session_id}/stories/override")
    def story_override(session_id: str,
                       payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Compact browser adapter over the explicit story resource routes."""
        known_session(session_id)
        action = payload.get("action")
        ids = payload.get("ids", [payload.get("id")])
        if (not isinstance(ids, list) or not ids
                or not all(isinstance(value, str) and value for value in ids)):
            raise HTTPException(status_code=422, detail="one or more story ids are required")
        if action == "delete":
            package: dict[str, Any] | None = None
            for story_id in ids:
                package = delivery_call(
                    lambda story_id=story_id: app.state.story_service.delete_story(
                        session_id, story_id
                    )
                )
            return package or {}
        if action == "merge":
            return delivery_call(
                lambda: app.state.story_service.merge_stories(
                    session_id, ids[0], ids[1:]
                )
            )
        if action == "edit":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise HTTPException(status_code=422, detail="edit text is required")
            return delivery_call(
                lambda: app.state.story_service.update_story(
                    session_id, ids[0], {"i_want": text}
                )
            )
        raise HTTPException(status_code=422, detail="action must be edit, delete, or merge")

    @app.get("/api/config/status")
    def configuration_status() -> dict[str, Any]:
        provider_name = app.state.provider.name
        provider_ready = (
            provider_name in {"ollama", "mock"}
            or (provider_name == "groq" and bool(config.GROQ_API_KEY))
            or (provider_name == "anthropic" and bool(config.ANTHROPIC_API_KEY))
        )
        if app.state.jira_client is not None:
            jira = app.state.jira_client.config.safe_dict()
        else:
            jira = {
                "configured": all(os.environ.get(key, "").strip() for key in (
                    "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"
                )),
                "base_url": os.environ.get("JIRA_BASE_URL", "").strip(),
                "project_key": os.environ.get("JIRA_PROJECT_KEY", "").strip(),
            }
        return {
            "provider": {"name": provider_name, "configured": provider_ready},
            "local_only": provider_name in {"ollama", "mock"},
            "asr": {
                "status": "ready" if (
                    config.OFFLINE_MODEL_DIR.is_dir()
                    and config.STREAMING_MODEL_DIR.is_dir()
                ) else "models_missing",
                "ready": (
                    config.OFFLINE_MODEL_DIR.is_dir()
                    and config.STREAMING_MODEL_DIR.is_dir()
                ),
            },
            "jira": jira,
        }

    @app.get("/api/jira/status")
    async def jira_status() -> dict[str, Any]:
        client, owned = jira_for()
        try:
            return await asyncio.to_thread(delivery_call, client.status)
        finally:
            if owned:
                client.close()

    @app.post("/api/session/{session_id}/jira/preview")
    async def jira_preview(session_id: str,
                           payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        known_session(session_id)
        project_key = payload.get("project_key", "")
        if not isinstance(project_key, str):
            raise HTTPException(status_code=422, detail="project_key must be a string")
        scope = payload.get("scope", "all")
        if scope not in {"all", "selected"}:
            raise HTTPException(status_code=422, detail="scope must be all or selected")
        story_ids = payload.get("story_ids") if scope == "selected" else None
        if scope == "selected" and not story_ids:
            raise HTTPException(
                status_code=422, detail="select at least one story for selected scope"
            )
        # Preview is a pure local plan. Do not require credentials or contact a
        # Jira site merely to let the analyst inspect issue fields. When Jira is
        # not configured, a non-routable placeholder client supplies only the
        # project/issue-type configuration consumed by JiraSyncService.preview.
        try:
            client, owned = jira_for(project_key)
        except HTTPException as exc:
            if exc.status_code != 503 or not project_key.strip():
                raise
            client = JiraCloudClient(JiraConfig(
                base_url="https://preview.invalid",
                email="",
                api_token="",
                project_key=project_key.strip().upper(),
                epic_issue_type=os.environ.get("JIRA_EPIC_ISSUE_TYPE", "Epic"),
                story_issue_type=os.environ.get("JIRA_STORY_ISSUE_TYPE", "Story"),
            ))
            owned = True
        try:
            result = await asyncio.to_thread(
                delivery_call,
                lambda: JiraSyncService(app.state.delivery_repo, client).preview(
                    session_id, story_ids=story_ids
                ),
            )
        finally:
            if owned:
                client.close()
        result["issues"] = [_jira_issue_view(item) for item in result["operations"]]
        result["story_ids"] = story_ids
        return result

    @app.post("/api/session/{session_id}/jira/sync")
    @app.post("/api/session/{session_id}/jira/export")
    async def jira_sync(session_id: str,
                        payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        known_session(session_id)
        project_key = payload.get("project_key", "")
        if not isinstance(project_key, str):
            raise HTTPException(status_code=422, detail="project_key must be a string")
        dry_run = payload.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise HTTPException(status_code=422, detail="dry_run must be a boolean")
        story_ids = payload.get("story_ids")
        supplied_preview = payload.get("preview")
        if story_ids is None and isinstance(supplied_preview, dict):
            story_ids = supplied_preview.get("story_ids")
        client, owned = jira_for(project_key)
        try:
            result = await asyncio.to_thread(
                delivery_call,
                lambda: JiraSyncService(app.state.delivery_repo, client).sync(
                    session_id, dry_run=dry_run, story_ids=story_ids
                ),
            )
        finally:
            if owned:
                client.close()
        result["issues"] = [_jira_issue_view(item) for item in result["operations"]]
        result["created_count"] = result.get("counts", {}).get("create", 0)
        return result

    @app.get("/api/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        return app.state.store.list_sessions()

    @app.post("/api/session/{session_id}/override")
    def override(session_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        known_session(session_id)
        if payload.get("action") not in {"pin", "dismiss", "edit"}:
            raise HTTPException(status_code=422, detail="action must be pin, dismiss, or edit")
        if not isinstance(payload.get("kind"), str) or not isinstance(payload.get("id"), str):
            raise HTTPException(status_code=422, detail="kind and id are required strings")
        app.state.store.append_override(session_id, payload)
        state, rev = app.state.store.load_state(session_id)
        updated = json.loads(json.dumps(state))
        _apply_overrides(updated, state, [payload])
        rev += 1
        app.state.store.snapshot_state(session_id, updated, rev)
        return {"state": updated, "rev": rev}

    @app.websocket("/ws/session/{session_id}")
    async def session_socket(websocket: WebSocket, session_id: str) -> None:
        try:
            app.state.store.session_dir(session_id)
        except (KeyError, ValueError):
            await websocket.close(code=4404)
            return
        await websocket.accept()
        loop = asyncio.get_running_loop()
        events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        running = False

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(events.put_nowait, event)

        def on_partial(text: str, utterance_id: int) -> None:
            emit({"type": "partial", "text": text, "utterance_id": utterance_id})

        def on_final(utterance: Utterance) -> None:
            app.state.store.append_utterance(session_id, utterance)
            emit({"type": "final", **utterance.to_json(), "utterance_id": utterance.id})
            state = app.state.intelligence.maybe_analyze(session_id)
            if state is not None:
                _state, rev = app.state.store.load_state(session_id)
                emit({"type": "state", "state": state, "rev": rev})

        async def send_events() -> None:
            while True:
                event = await events.get()
                if event is None:
                    return
                await websocket.send_json(event)

        sender = asyncio.create_task(send_events())
        asr: AsrEngine | None = None
        try:
            try:
                asr = await asyncio.to_thread(
                    app.state.asr_factory, on_partial=on_partial, on_final=on_final
                )
            except Exception as exc:
                emit({"type": "error", "where": "asr", "message": str(exc)})
                return
            emit({"type": "ready"})
            emit({"type": "status", "asr": "running", "engine": "idle",
                  "provider": app.state.provider.name})

            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                raw = message.get("bytes")
                if raw is not None:
                    if not running:
                        continue
                    if len(raw) % 4:
                        emit({"type": "error", "where": "asr",
                              "message": "PCM binary payload length must be a multiple of 4"})
                        continue
                    pcm = np.frombuffer(raw, dtype="<f4").copy()
                    if not np.all(np.isfinite(pcm)):
                        emit({"type": "error", "where": "asr",
                              "message": "PCM payload contains NaN or infinity"})
                        continue
                    try:
                        await asyncio.to_thread(asr.feed, pcm)
                    except Exception as exc:
                        running = False
                        emit({"type": "error", "where": "asr", "message": str(exc)})
                    continue

                text = message.get("text")
                try:
                    control = json.loads(text or "")
                except json.JSONDecodeError:
                    emit({"type": "error", "where": "asr", "message": "invalid control JSON"})
                    continue
                command = control.get("type")
                if command == "start":
                    running = True
                elif command == "stop":
                    running = False
                    try:
                        await asyncio.to_thread(asr.flush)
                    except Exception as exc:
                        emit({"type": "error", "where": "asr", "message": str(exc)})
                        continue
                    state = await asyncio.to_thread(app.state.intelligence.analyze, session_id)
                    if state is not None:
                        _state, rev = app.state.store.load_state(session_id)
                        emit({"type": "state", "state": state, "rev": rev})
                    else:
                        emit({"type": "error", "where": "provider",
                              "message": "final analysis did not return valid state"})
                elif command == "ping":
                    emit({"type": "pong"})
                else:
                    emit({"type": "error", "where": "asr",
                          "message": f"unknown control type {command!r}"})
        except WebSocketDisconnect:
            pass
        finally:
            if running and asr is not None:
                try:
                    await asyncio.to_thread(asr.flush)
                except Exception:
                    pass
            events.put_nowait(None)
            try:
                await sender
            except (WebSocketDisconnect, RuntimeError):
                sender.cancel()

    web_dir = Path(__file__).resolve().parent / "web"
    if web_dir.is_dir():
        # Mounted last so API and WebSocket routes retain precedence.
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


def _jira_issue_view(operation: dict[str, Any]) -> dict[str, Any]:
    """Small, secret-free shape consumed by the browser preview."""
    fields = operation.get("fields", {})
    parent = fields.get("parent", {}) if isinstance(fields, dict) else {}
    return {
        "local_id": operation.get("local_id", ""),
        "issue_type": str(operation.get("kind", "issue")).title(),
        "summary": fields.get("summary", "") if isinstance(fields, dict) else "",
        "parent": parent.get("key", "") if isinstance(parent, dict) else "",
        "action": operation.get("action", ""),
        "jira_key": operation.get("jira_key"),
    }


app = create_app()


def main() -> None:  # pragma: no cover - exercised by launchers
    import uvicorn

    uvicorn.run("src.server:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
