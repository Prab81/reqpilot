# ReqPilot

ReqPilot is a local-first requirements elicitation copilot for business analysts.
It listens to an in-room workshop through the computer microphone or imports an
existing Teams/Copilot transcript, then maintains a live transcript, visual
requirements canvas, targeted clarifying questions, a traceable BRD, and
delivery-ready epics and user stories.

ReqPilot runs beside Microsoft Teams rather than inside it. It does not join a
meeting, install a Teams application, or capture system audio. For remote work
meetings, use the organisation-approved Teams transcript export after the
meeting. For in-person workshops, use live microphone mode with participant
knowledge and consent.

## Product modes

### Live workshop

- Browser microphone capture with explicit permission.
- Streaming Zipformer partial transcript and punctuated Parakeet final text.
- Live one-page canvas containing summary, requirements, decisions, gaps,
  process flows, and metrics.
- Copilot questions targeted at actors, data, volumes, exceptions, NFRs, and
  acceptance criteria.
- Pause/resume and analyst pin/edit/dismiss/asked/answered/parked controls.

### Transcript import

- Paste Teams/Copilot text or upload TXT, Microsoft Teams VTT, or DOCX.
- Speaker labels and VTT timestamps are retained when supplied.
- The same canvas, question, BRD, story, and traceability pipeline runs without
  constructing microphone or speech-model components.

### Delivery

- BRD preview plus Markdown and styled Word/DOCX exports.
- Epics and user stories with acceptance criteria and source evidence.
- Analyst edit, merge, and delete controls that persist across regeneration.
- Jira preview and idempotent Jira Cloud REST export. Re-export updates the
  issues recorded for the session rather than creating duplicates.

## Windows quick start

Requirements: Python 3.11 or newer. Ollama is recommended for private, local
analysis; Groq and Anthropic are supported alternatives.

1. Copy `.env.example` to `.env` and select a provider.
2. Double-click `run_windows.bat`.
3. Open <http://127.0.0.1:8765>.
4. Choose **Live session** or **Import transcript**.

The first connected installation creates `.venv`, installs Python packages,
and downloads the speech models if they are not already available. A bundle
created by `scripts/build_offline_bundle.py` includes platform wheels and
models so installation can run without internet access.

## macOS quick start

```bash
cp .env.example .env
chmod +x run_mac.sh
./run_mac.sh
```

Open <http://127.0.0.1:8765> and allow microphone access when live mode is used.
Build an offline macOS bundle on a Mac with the same architecture as the target
machine because Python wheels are platform-specific.

macOS notes:

- Python 3.11+ is required; on a fresh Mac, `brew install python@3.12` (or
  newer) is the simplest route. `run_mac.sh` creates `.venv`, installs
  dependencies (sherpa-onnx publishes Apple Silicon arm64 wheels), fetches
  models if needed, and starts the server — no other setup.
- Use Chrome or Edge for live capture if possible: they honour the 16 kHz
  `AudioContext` request directly. Safari works too — the capture layer
  detects the actual sample rate and resamples in the worklet.
- Microphone permission is granted to the *browser*, not to ReqPilot. If the
  prompt never appears, check System Settings → Privacy & Security →
  Microphone and enable the browser there, then reload the page.
- The speech engine itself is portable Python (no native shell) — nothing in
  `src/` requires macOS-specific changes. If anything platform-specific ever
  surfaces, it belongs in the pluggable audio-source boundary, not the engine.

## Speech models

ReqPilot needs two sherpa-onnx model sets. Three ways to get them, checked in
this order by `src/config.py` / `scripts/fetch_models.py`:

1. **Automatic (default).** The launcher downloads both sets from the official
   `k2-fsa/sherpa-onnx` GitHub releases into `./models/` on first run. No
   action needed on an unrestricted network.
2. **From your own GitHub releases (office laptop / restricted networks).**
   Both models are mirrored under this account so no third-party download is
   required — grab the files in a browser and place them as follows:
   - **Parakeet (finals)** — assets of
     [`Prab81/inkvoice` release v0.1.0](https://github.com/Prab81/inkvoice/releases/tag/v0.1.0):
     `encoder.int8.onnx`, `decoder.int8.onnx`, `joiner.int8.onnx`, `tokens.txt`
     → put all four in `models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/`
   - **Zipformer (live partials)** — assets of
     [`Prab81/reqpilot` release v0.1.0](https://github.com/Prab81/reqpilot/releases/tag/v0.1.0):
     `encoder-epoch-99-avg-1.int8.onnx`, `decoder-epoch-99-avg-1.int8.onnx`,
     `joiner-epoch-99-avg-1.int8.onnx`, `tokens.txt`
     → put all four in `models/sherpa-onnx-streaming-zipformer-en-2023-06-21/`
   Folder names matter; create them under the repo's `models/` directory (it
   is git-ignored). Alternatively put them anywhere and point
   `REQPILOT_OFFLINE_MODEL_DIR` / `REQPILOT_STREAMING_MODEL_DIR` at the
   directories in `.env`.
3. **Existing InkVoice checkout (dev machine).** If the InkVoice project is
   present at its standard path, both model directories are auto-detected and
   nothing is downloaded.

The offline bundle (`scripts/build_offline_bundle.py`) embeds the models, so a
bundled install needs none of the above.

## Local-only configuration

Example using Ollama:

```dotenv
REQPILOT_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
```

Speech recognition and session storage stay local. With Ollama selected, the
requirements analysis also stays local. Groq or Anthropic modes send the text
included in an analysis prompt to the selected provider; audio is never sent to
the language-model provider.

## Jira configuration

Jira export is disabled until all required variables are configured locally:

```dotenv
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your.account@example.com
JIRA_API_TOKEN=replace-with-a-scoped-token
JIRA_PROJECT_KEY=ABC
```

Secrets belong in `.env`, which is ignored by Git. The UI reports whether Jira
is ready but never returns the token. Use preview before export to review the
exact epic/story payloads.

## Verification

```powershell
python -m pytest -q
$env:REQPILOT_REAL_ASR_TEST='1'
python -m pytest tests/test_decoder.py::test_real_models_decode_known_english_fixture -q
```

The normal suite is cloud-free. Provider and Jira contract tests use simulated
HTTP transports; real-service calls are opt-in.

Run the readiness diagnostic before a workshop, optionally including the live
server probe:

```powershell
python -m scripts.diagnose --server
```

## Offline bundle

Build on the same operating system and CPU architecture as the destination:

```powershell
python -m scripts.build_offline_bundle
```

The resulting zip under `dist/` contains the application, current-platform
wheelhouse, speech models, documentation, and a SHA-256 checksum in the build
output. Model files dominate the archive size and are already quantised, so
splitting the zip for transport is usually more effective than trying stronger
compression.

```powershell
python -m scripts.bundle_parts split dist\ReqPilot-offline-windows-amd64.zip --part-mb 95
python -m scripts.bundle_parts reassemble dist\ReqPilot-offline-windows-amd64.zip-parts\ReqPilot-offline-windows-amd64.zip.parts.json
```

Each part and the reconstructed archive are SHA-256 checked before use.

The verified Windows build is written to
`dist/ReqPilot-offline-windows-amd64.zip`; its companion `-parts` directory is
ready for constrained file-transfer channels.

## Data and security

- Sessions are stored under `data/` unless `REQPILOT_DATA_DIR` is set.
- API keys and Jira credentials are loaded from environment variables/`.env`.
- Uploaded transcript files are parsed in memory; the original upload is not
  retained.
- Imports have type, path, archive-safety, and size checks.
- The server binds to `127.0.0.1` by default and is not exposed to the network.
- System-audio loopback remains deliberately deferred behind the pluggable
  audio-source boundary.

## Project documentation

- `docs/PRD.md` - approved product requirements and phase decisions.
- `docs/ARCHITECTURE.md` - interface and persistence contracts.
- `docs/STORIES.md` - user stories and acceptance criteria.
- `docs/TEST_SCENARIOS.md` - executable scenario catalogue.
- `docs/BUILD_LOG.md` - delivered work and verification evidence.
- `docs/CONTEXT.md` - append-only decision log.

## Known external verification items

- Physical microphone capture requires a human to grant browser permission and
  speak into the chosen device.
- The macOS launcher and microphone path must be checked on actual Mac hardware.
- A real Jira export requires the user's Jira site, project, and scoped token.
