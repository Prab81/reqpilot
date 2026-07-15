# ARCHITECTURE — ReqPilot (Phase-Live)

> Living document. This version is the build contract for Phase-Live (mic-only live copilot).
> Build agents: treat the interfaces in this file as authoritative; do not invent alternatives.

## System overview

```
Browser (Chrome/Edge/Safari — served from localhost)
│  getUserMedia → AudioWorklet → downsample to 16 kHz mono float32
│  ── binary PCM frames ──►  WS /ws/session/{id}
│  ◄── JSON events ─────────  (partial | final | state | status)
▼
FastAPI server (Python 3.14, uvicorn)               src/server.py
├── AudioGateway: WS endpoint, feeds AudioSource abstraction
│     MicSource (browser PCM)  [future: LoopbackSource — flag only]
├── VAD segmenter (energy-based, pre-roll/hangover)  src/audio/vad.py
├── ASR engine (ported from InkVoice)                src/audio/decoder.py
│     streaming Zipformer → live partials
│     Parakeet-TDT-0.6b-v3 int8 → punctuated finals (chunked ≤19 s decode)
├── Intelligence engine                              src/intelligence/
│     rolling utterance log → periodic LLM pass → SessionState JSON
│     providers: Groq (default) | Anthropic | Ollama  (pluggable)
├── BRD generator (post-session)                     src/intelligence/brd.py
└── Session store (JSONL, local only)                src/sessions/store.py
```

## Repository layout

```
src/
  server.py               FastAPI app: static serving, WS, REST
  config.py               paths, model dirs, provider selection (.env)
  audio/
    vad.py                EnergyVAD: continuous stream → utterance segments
    decoder.py            UtteranceDecoder (InkVoice port, continuous mode)
    engine.py             AsrEngine: VAD + decoder orchestration, thread-safe
  intelligence/
    state.py              SessionState dataclasses + (de)serialization
    providers.py          LlmProvider ABC; GroqProvider, AnthropicProvider, OllamaProvider, MockProvider
    prompts.py            all prompt templates (single module — reviewable)
    engine.py             IntelligenceEngine: incremental analysis loop
    brd.py                BRD markdown generator (post-session)
  sessions/
    store.py              SessionStore: append events, snapshot state, list/load
  web/
    index.html            three-pane UI (transcript | canvas | copilot)
    app.js                WS client, render loop, Mermaid + chart rendering
    audio-capture.js      getUserMedia + AudioWorklet + downsampler
    worklet.js            AudioWorkletProcessor (raw frames → main thread)
    style.css
tests/                    mirrors src/ (pytest)
  fixtures/               WAV + transcript fixtures, canned LLM responses
run_windows.bat  run_mac.sh  requirements.txt  .env.example
```

## Interface contracts

### WS protocol — `/ws/session/{session_id}`
Client→server: **binary** messages = float32 mono 16 kHz PCM frames (raw bytes,
any frame size; server buffers). **Text** messages = JSON control:
`{"type":"start"}` · `{"type":"stop"}` · `{"type":"ping"}`

Server→client, one JSON object per text message:
```json
{"type":"ready"}
{"type":"partial","text":"...","utterance_id":7}
{"type":"final","text":"...","utterance_id":7,"t0":123.4,"t1":131.9}
{"type":"state","state":{ ...SessionState JSON... },"rev":12}
{"type":"status","asr":"running","engine":"analyzing","provider":"groq"}
{"type":"error","where":"asr|engine|provider","message":"..."}
{"type":"pong"}
```

### SessionState JSON (canvas + copilot contract)
```json
{
  "title": "string",
  "summary": ["bullet", "..."],
  "requirements": [{"id":"R1","text":"...","status":"captured|clarifying|confirmed","evidence_utterances":[3,9]}],
  "decisions":    [{"id":"D1","text":"...","evidence_utterances":[12]}],
  "open_questions":[{"id":"Q1","text":"...","status":"suggested|asked|answered|parked","requirement_id":"R1","category":"actors|data|volumes|exceptions|nfr|acceptance|general"}],
  "diagrams":     [{"id":"G1","kind":"flowchart|process","title":"...","mermaid":"flowchart TD; ...","evidence_utterances":[5,6]}],
  "metrics":      [{"id":"M1","title":"...","kind":"bar|pie","labels":["..."],"values":[1,2],"evidence_utterances":[8]}],
  "gaps":         [{"id":"X1","text":"...","category":"actors|definitions|nfr|edge_cases|conflict","evidence_utterances":[4]}]
}
```
Rules: engine returns the FULL updated state each pass (server stamps `rev`).
IDs are stable across passes — the LLM is given previous state and must
preserve IDs of unchanged items. User edits (pin/dismiss) are held server-side
as overrides and re-applied after each engine pass (AC5 of STORY-004).

### LlmProvider ABC (`providers.py`)
```python
class LlmProvider(ABC):
    name: str
    def complete_json(self, system: str, user: str, schema_hint: str, max_tokens: int = 4096) -> dict: ...
```
`complete_json` must parse/repair to a dict, raising `ProviderError` on failure
after one retry. `MockProvider(responses: list[dict])` replays canned dicts — all
engine tests use it; no test may hit a real API.

### AsrEngine (`audio/engine.py`)
```python
class AsrEngine:
    def __init__(self, on_partial: Callable[[str,int],None], on_final: Callable[[Utterance],None]): ...
    def feed(self, pcm: np.ndarray) -> None      # any-size float32 16k frames
    def flush(self) -> None                      # force-finalize current utterance
```
Continuous mode: EnergyVAD segments speech (pre-roll 300 ms, hangover 800 ms,
max utterance 45 s → forced cut at silence or hard max). Each segment runs the
InkVoice dual-model path: Zipformer partials while open, Parakeet chunked final
on close. `Utterance = {id:int, t0:float, t1:float, text:str}` (session-relative seconds).

### IntelligenceEngine cadence
Triggered when ≥25 s of new final-utterance content OR ≥6 new utterances since
last pass, min 15 s between passes; also on `stop` (final pass) and on demand
(`POST /api/session/{id}/analyze`). Each pass sends: previous SessionState +
new utterances (+ last 10 finalized for context) → prompt in `prompts.py` →
`complete_json` → validated (see state.py validators; invalid Mermaid → item
dropped to `gaps` note, never sent broken to the client).

### REST
```
POST /api/session                → {id}                (create)
GET  /api/session/{id}/state     → SessionState
POST /api/session/{id}/analyze   → force engine pass
POST /api/session/{id}/brd       → {markdown}          (BRD generation)
GET  /api/sessions               → list summaries
POST /api/session/{id}/override  → pin/edit/dismiss an item {kind,id,action,text?}
```

## Model + provider configuration (`config.py` / `.env`)
- `REQPILOT_OFFLINE_MODEL_DIR` / `REQPILOT_STREAMING_MODEL_DIR` — default to the
  InkVoice model dirs (already on disk):
  `V:/AI/Netriq InkVoice/spikes/m0_asr/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`
  `V:/AI/Netriq InkVoice/spikes/streaming_zipformer/sherpa-onnx-streaming-zipformer-en-2023-06-21`
  `scripts/fetch_models.py` (adapted from InkVoice) downloads them when absent (fresh machine / Mac).
- `REQPILOT_PROVIDER` = groq | anthropic | ollama (default groq); keys via `GROQ_API_KEY` etc. `.env` never committed.

## Key decisions embedded here
1. **Browser mic capture** (not PortAudio/sounddevice): avoids the InkVoice
   M0 finding (PortAudio → silence on Bluetooth LE Audio mics on Windows);
   browser handles WASAPI/CoreAudio + permission UX; Win+Mac parity free.
2. **InkVoice dual-model ASR port**: Parakeet finals (accuracy + punctuation)
   + Zipformer partials (smooth live text); chunked ≤19 s offline decodes
   (the >20 s degradation fix) carried over verbatim.
3. **Server-side session state with client render**: canvas is a pure renderer
   of SessionState; all intelligence server-side → transcript-import phase
   reuses everything except the audio path.
4. **Sequential engine passes with full-state output**: simpler than diffing;
   state is small (a meeting's worth of structured items, not the transcript).

## Deliberately deferred
- System-audio loopback source (REQ-002, flag), diarization beyond single
  channel, DOCX export (markdown first), Jira export (Phase-Delivery),
  auth (localhost, single user).
