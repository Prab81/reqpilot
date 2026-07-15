"""ReqPilot localhost REST/WebSocket server."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from src import config
from src.audio.engine import AsrEngine
from src.intelligence.brd import generate_brd
from src.intelligence.engine import IntelligenceEngine, _apply_overrides
from src.intelligence.providers import LlmProvider, get_provider
from src.intelligence.state import Utterance
from src.sessions.store import SessionStore


def create_app(
    *,
    store: SessionStore | None = None,
    provider: LlmProvider | None = None,
    asr_factory: Callable[..., AsrEngine] | None = None,
) -> FastAPI:
    app = FastAPI(title="ReqPilot", version="0.1.0")
    app.state.store = store or SessionStore(config.DATA_DIR)
    app.state.provider = provider or get_provider()
    app.state.intelligence = IntelligenceEngine(app.state.provider, app.state.store)
    app.state.asr_factory = asr_factory or AsrEngine

    def known_session(session_id: str) -> None:
        try:
            app.state.store.session_dir(session_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/session")
    def create_session(payload: dict[str, Any] | None = Body(default=None)) -> dict[str, str]:
        title = payload.get("title", "") if isinstance(payload, dict) else ""
        return {"id": app.state.store.create_session(str(title))}

    @app.get("/api/session/{session_id}/state")
    def get_state(session_id: str) -> dict[str, Any]:
        known_session(session_id)
        state, _rev = app.state.store.load_state(session_id)
        return state

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


app = create_app()


def main() -> None:  # pragma: no cover - exercised by launchers
    import uvicorn

    uvicorn.run("src.server:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
