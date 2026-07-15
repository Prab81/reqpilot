# ReqPilot Build Log

This log records implementation decisions, verification evidence, and remaining
external checks. Product scope and rationale remain authoritative in `PRD.md`
and `CONTEXT.md`; this file records what was actually built and tested.

## 2026-07-16 - Phase-Live foundation completed

### Delivered

- Browser microphone capture using `getUserMedia` and an `AudioWorklet`.
- Float32, mono, 16 kHz PCM transport over the session WebSocket.
- Continuous energy VAD with 300 ms pre-roll, 800 ms hangover, and forced
  segmentation for long utterances.
- InkVoice-derived dual-model speech recognition:
  - streaming Zipformer partial text;
  - Parakeet-TDT punctuated final text;
  - final decoding split into chunks no longer than 19 seconds.
- FastAPI REST and WebSocket application, local JSONL event storage, atomic
  state snapshots, and restart-safe analysis watermarks.
- Pluggable Groq, Anthropic, Ollama, and mock language-model providers.
- Validated live state containing summaries, requirements, decisions,
  questions, process diagrams, metrics, and elicitation gaps.
- Server-enforced stable IDs and durable analyst edit/dismiss/pin/status
  overrides.
- Responsive three-pane interface for transcript, visual canvas, and copilot
  prompts, including Mermaid rendering and chart fallbacks.
- Markdown BRD generation with transcript timestamp evidence.
- Windows and macOS launchers plus ASR model bootstrap.

### Verification evidence

- Full automated suite after integration: 56 passed, 1 opt-in real-model test
  skipped, 1 dependency deprecation warning.
- Opt-in real Parakeet/Zipformer test: passed.
- Real model smoke using the InkVoice fixtures:
  - models loaded in approximately 2 seconds;
  - 3.845 seconds of audio decoded in approximately 0.19 seconds;
  - ten streaming partial updates emitted;
  - final transcript matched the expected punctuated sentence.
- Real local Ollama analysis using `qwen3:8b` over eight scripted meeting
  utterances completed successfully and produced six summary bullets, five
  requirements, four targeted questions, one process diagram, and one gap.
- Live server returned HTTP 200 from `http://127.0.0.1:8765` and accepted
  WebSocket sessions, emitting `ready` and provider status events.

### External checks still pending

- A human must accept the browser microphone permission and speak into the
  physical device to complete the final hardware loop. Automated browsers
  cannot safely accept that browser-level permission prompt.
- The macOS launcher and microphone path require execution on an actual Mac.

## 2026-07-16 - Complete-product expansion started

The approved goal was expanded from the live foundation to the entire local MVP.
Work streams now cover:

1. TXT, VTT, DOCX, and pasted transcript import.
2. Continuously viewable BRD plus Markdown and styled DOCX export.
3. Epic and user-story generation, editing, persistence, and traceability.
4. Jira preview and idempotent REST export behind environment configuration.
5. Complete multi-mode UI, saved-session restoration, diagnostics, packaging,
   and regression verification.

External credentials are not embedded in source control. Jira creation will be
contract-tested against a simulated Jira API and left ready for a real site URL,
account email, API token, and project key.

## 2026-07-16 - Complete local MVP integrated

### Delivered

- Safe paste/TXT/VTT/DOCX import with speaker and timestamp preservation.
- Unified saved-session workspace for live and imported meetings.
- BRD preview, Markdown export, and structured styled DOCX export.
- Epic/story generation, edit, merge, delete, stable identifiers, persisted
  overrides, acceptance criteria, and transcript traceability.
- Jira Cloud v3 preview and idempotent sync using modern parent relationships.
- Responsive accessible UI covering entry, live capture, import, canvas,
  questions, BRD, stories, Jira, provider status, and session restoration.
- Offline bundle builder, checksummed archive splitting/reassembly, diagnostics,
  launchers, operations guide, and security notes.
- Safe Mermaid edge-label normalization for common local-model output without
  allowing directives, links, styling, scripts, subgraphs, or comments.

### Verification evidence

- Automated suite: 114 passed, 1 opt-in real-model test skipped.
- Real ASR opt-in fixture passed in the earlier foundation gate.
- Real local Ollama end-to-end import of 30 loan-workshop utterances:
  - 30 transcript utterances, 6 summary bullets, 9 requirements, 6 questions;
  - 1 epic, 3 stories, and 6 acceptance criteria;
  - BRD Markdown: 5,851 characters;
  - Word export: 43,263 bytes.
- Readiness diagnostic: Python, both ASR model trees, local storage, Ollama, and
  the running server all ready. Jira correctly reported optional/unconfigured.
- DOCX structural QA: no accessibility findings, real heading styles, four
  header-row tables, fixed table geometry, Letter portrait layout, one-inch
  margins, and separate header/footer parts.
- Verified final saved demo: 30 utterances, 18 requirements, 4 targeted
  questions, a 9-line process diagram, 2 metrics, 3 epics, 6 stories, and 12
  acceptance criteria. Its BRD contains 6,607 Markdown characters and a
  44,082-byte DOCX.
- Offline Windows package: 37 wheels, both ASR model trees, 125 ZIP entries;
  clean no-index virtual-environment installation and bundled-model diagnostics
  passed. Eleven split parts reassembled to the exact original SHA-256.

### External checks still pending

- Visual page-image DOCX rendering could not run because LibreOffice is not
  installed; Word automation was not reliable in this non-interactive session.
  Structural and accessibility QA passed.
- Physical microphone capture needs a person to grant browser permission and
  speak into the selected device.
- macOS and real Jira-site verification need the corresponding hardware and
  credentials.

## 2026-07-16 - Backlog file exports and BRD diagram embedding

### Delivered

- `src/delivery/stories_export.py`: `build_stories_docx` renders the story
  package as a delivery-backlog Word document in the BRD's visual language
  (shared style/table helpers, US Letter, one-inch margins, header/footer with
  page field). Each epic is a Heading-1 section; each story is a Heading-2
  section with the As-a/I-want/So-that narrative, an ID/Given/When/Then
  acceptance-criteria table, and a traceability line combining requirement IDs
  with mm:ss transcript evidence.
- `stories_csv` flattens the same package into an RFC 4180 CSV (CRLF, csv-module
  quoting) with the header `Issue Type,Key,Summary,Description,Acceptance
  Criteria,Epic,Requirements,Evidence` and one row per epic and per story.
- New routes `GET /api/session/{id}/stories.docx` and `.csv` return 404 with a
  clear detail until stories are generated, then serve
  `reqpilot-backlog-{id}.docx/.csv` with correct content types.
- `POST /api/session/{id}/brd.docx` accepts `{"diagrams":[{"id","png_base64"}]}`.
  The browser rasterizes the Mermaid SVGs already rendered on the canvas
  (`svgToPngBase64`, 2x scale, white background) and posts them; the export
  embeds each verified PNG at six inches wide with a caption and evidence line.
  Invalid base64, non-PNG bytes, or unknown diagram ids silently keep the
  existing text-only line; payloads over 20 MB are rejected with 413. The bare
  GET route is unchanged.
- Epics & stories tab gained "Download Word backlog" and "Download CSV"
  controls, disabled until stories exist.

### Verification

- Full automated suite: 125 passed, 1 skipped (opt-in real-ASR fixture).
- New coverage: backlog DOCX structure and traceability, CSV header/rows/
  quoting/CRLF, export-route 404-then-200 contract, BRD POST embedding with a
  generated minimal PNG, garbage-payload fallback, and the 413 size cap.
