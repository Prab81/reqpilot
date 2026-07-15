import numpy as np
from fastapi.testclient import TestClient

from src.intelligence.providers import MockProvider
from src.intelligence.state import Utterance, empty_state
from src.server import create_app
from src.sessions.store import SessionStore


class FakeAsr:
    def __init__(self, on_partial, on_final):
        self.on_partial = on_partial
        self.on_final = on_final
        self.fed = False

    def feed(self, pcm):
        self.fed = True
        self.on_partial("live partial", 1)

    def flush(self):
        if self.fed:
            self.on_final(Utterance(1, 0.1, 1.1, "final transcript"))
            self.fed = False


def state_response():
    state = empty_state()
    state["title"] = "Checkout discovery"
    state["summary"] = ["Captured checkout needs"]
    return state


def build(tmp_path, responses=None):
    store = SessionStore(tmp_path / "data")
    provider = MockProvider(list(responses or []))
    app = create_app(store=store, provider=provider, asr_factory=FakeAsr)
    return TestClient(app), store


def test_rest_create_list_state_analyze_and_override(tmp_path):
    client, store = build(tmp_path, [state_response()])
    sid = client.post("/api/session", json={"title": "Discovery"}).json()["id"]
    assert client.get(f"/api/session/{sid}/state").json() == empty_state()

    analyzed = client.post(f"/api/session/{sid}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["rev"] == 1
    assert client.get("/api/sessions").json()[0]["id"] == sid

    current = analyzed.json()["state"]
    current["requirements"] = [{"id": "R1", "text": "Old", "status": "captured",
                                 "evidence_utterances": []}]
    store.snapshot_state(sid, current, 2)
    edited = client.post(f"/api/session/{sid}/override", json={
        "kind": "requirement", "id": "R1", "action": "edit", "text": "New"
    })
    assert edited.status_code == 200
    assert edited.json()["state"]["requirements"][0]["text"] == "New"


def test_websocket_binary_pcm_partial_final_state_and_ping(tmp_path):
    client, store = build(tmp_path, [state_response()])
    sid = client.post("/api/session").json()["id"]

    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        first = ws.receive_json()
        second = ws.receive_json()
        assert {first["type"], second["type"]} == {"ready", "status"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "start"})
        ws.send_bytes((np.ones(320, dtype="<f4") * 0.02).tobytes())
        partial = ws.receive_json()
        assert partial == {"type": "partial", "text": "live partial", "utterance_id": 1}
        ws.send_json({"type": "stop"})
        final = ws.receive_json()
        state = ws.receive_json()
        assert final["type"] == "final" and final["text"] == "final transcript"
        assert state["type"] == "state" and state["rev"] == 1

    assert store.load_utterances(sid)[0].text == "final transcript"


def test_websocket_rejects_malformed_pcm_without_calling_asr(tmp_path):
    client, _store = build(tmp_path)
    sid = client.post("/api/session").json()["id"]
    with client.websocket_connect(f"/ws/session/{sid}") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "start"})
        ws.send_bytes(b"abc")
        error = ws.receive_json()
        assert error["type"] == "error"
        assert "multiple of 4" in error["message"]
