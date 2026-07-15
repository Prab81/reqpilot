# ReqPilot architecture

This document describes the implemented local MVP. The browser is the user
interface, FastAPI owns the session and delivery workflows, and all durable
artifacts are stored below the configured local data directory.

## System overview

```text
Browser UI
  |-- Live: getUserMedia -> AudioWorklet -> 16 kHz mono PCM
  |-- Import: paste or upload TXT / VTT / DOCX
  |-- Render: transcript, canvas, questions, BRD, stories, Jira preview
  |
  +-- WebSocket /ws/session/{id} (live PCM + events)
  +-- REST /api/... (session, import, delivery, configuration)
          |
FastAPI server
  |-- Audio: energy VAD -> streaming Zipformer -> Parakeet finals
  |-- Intelligence: rolling transcript -> configured LLM -> validated state
  |-- Delivery: BRD Markdown/DOCX -> epics/stories -> Jira Cloud v3
  +-- Persistence: atomic JSON snapshots + JSONL transcript
```

## Source layout

```text
src/
  server.py                 FastAPI REST, WebSocket, static UI
  config.py                 environment and model paths
  audio/                    VAD, ASR decoders, live orchestration
  intelligence/             providers, prompts, state, BRD, analysis loop
  importers/                safe TXT, VTT, DOCX, and paste parsing
  delivery/                 stories, overrides, DOCX, Jira
  sessions/                 local session persistence
  web/                      accessible responsive browser application
scripts/
  fetch_models.py           model bootstrap
  diagnose.py               non-destructive readiness checks
  build_offline_bundle.py   source + wheelhouse + model archive
  bundle_parts.py           checksummed split/reassembly
```

## Live audio contract

The browser requests microphone access only after the analyst starts a live
session. An AudioWorklet downsamples browser audio to float32, mono, 16 kHz PCM
and sends binary frames to `/ws/session/{session_id}`.

Text control messages are `start`, `stop`, `pause`, `resume`, and `ping`.
Server events include `ready`, `partial`, `final`, `state`, `status`, `error`,
and `pong`. Audio is not retained; finalized utterances are persisted.

The server uses 300 ms VAD pre-roll and 800 ms hangover. Streaming Zipformer
produces partial text. Parakeet-TDT produces punctuated finals in chunks no
longer than 19 seconds.

## Import contract

`POST /api/session/import` accepts either multipart `file` or form `text`, plus
an optional title and filename. Input is capped at 10 MiB. Supported forms:

- plain text and copied Teams/Copilot text;
- WebVTT, including Teams cue metadata and speaker labels;
- DOCX paragraphs.

VTT timestamps are preserved. Other inputs receive deterministic synthetic
timestamps. DOCX parsing rejects unsafe ZIP paths, excessive archive expansion,
and malformed documents. The original upload is not retained.

## Intelligence state

Each analysis pass returns a full state containing title, summary,
requirements, decisions, open questions, process diagrams, metrics, and gaps.
IDs remain stable across passes. Analyst edits, pins, dismissals, and question
statuses are reapplied after every model response.

Model responses are untrusted. They are schema-checked before persistence.
Mermaid is restricted to a small flowchart allow-list; scripts, links, styling,
subgraphs, comments, and directives are rejected. Harmless unquoted edge labels
are normalized into the safe quoted form before validation.

## Provider boundary

`LlmProvider.complete_json()` is implemented by Groq, Anthropic, Ollama, and a
deterministic test provider. Speech always remains local. In Ollama mode the
analysis text remains local as well. Cloud modes send only prompt text to the
selected provider and require an explicit API key.

## Delivery model

The BRD builder produces Markdown and a styled Word document with source
timestamps. The story service produces epics and standard user stories with
2-5 acceptance criteria and requirement/evidence traceability. Story edits,
deletions, and merges are stored as overrides and survive regeneration.

Jira integration uses the Jira Cloud REST API v3. Preview never contacts Jira.
Sync creates parent epics before stories and records the resulting issue keys
in the session delivery snapshot. Later syncs update those keys instead of
creating duplicates. Secrets are loaded from the environment and never
returned by status endpoints.

## Persistence

Each session is stored under `REQPILOT_DATA_DIR` (default `data/sessions`):

```text
{session_id}/
  meta.json
  utterances.jsonl
  state.json
  overrides.jsonl          when analyst overrides exist
  delivery.json            story edits and Jira mappings
  exports/brd.docx         generated on request
```

Snapshots use atomic replacement. Analysis watermarks and ID high-water marks
are persisted so a restart does not replay or renumber existing content.

## Security boundaries

- The server binds to `127.0.0.1` by default.
- `.env`, session data, build output, and credentials are ignored by Git.
- Upload validation prevents path traversal and unsafe DOCX archive expansion.
- Mermaid and model JSON are allow-list validated before browser rendering.
- Jira export requires an explicit configured project and user action.
- System-audio loopback and automatic meeting joining are deliberately absent.

## API summary

```text
POST   /api/session
POST   /api/session/import
GET    /api/sessions
GET    /api/session/{id}/state
GET    /api/session/{id}/transcript
POST   /api/session/{id}/analyze
POST   /api/session/{id}/override
POST   /api/session/{id}/brd
GET    /api/session/{id}/brd.docx
POST   /api/session/{id}/stories/generate
GET    /api/session/{id}/stories
PATCH  /api/session/{id}/epics/{epic_id}
DELETE /api/session/{id}/epics/{epic_id}
PATCH  /api/session/{id}/stories/{story_id}
DELETE /api/session/{id}/stories/{story_id}
POST   /api/session/{id}/stories/merge
POST   /api/session/{id}/jira/preview
POST   /api/session/{id}/jira/sync
GET    /api/config/status
GET    /api/jira/status
```

## Deferred external validation

Physical microphone permission and audio quality require a human using the
actual device. The macOS launcher requires Mac hardware. Jira's contract is
automated, but a real sync requires the user's Jira credentials and project.
