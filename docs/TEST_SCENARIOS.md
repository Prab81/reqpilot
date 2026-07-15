# ReqPilot test scenarios

Last updated: 2026-07-16. Automated scenarios run with `python -m pytest -q`.
Cloud and Jira contract tests use simulated transports and do not send data.

| Area | Scenario | Evidence | Status |
|---|---|---|---|
| Live audio | 48 kHz browser frames become 16 kHz mono PCM | audio-capture checks | Pass |
| Live audio | pause/resume stops and restarts frame delivery | browser logic + WS contract | Pass |
| VAD | silence/speech/silence yields one segment with pre-roll/hangover | unit | Pass |
| ASR | known English WAV emits partials and correct punctuated final | opt-in real models | Pass |
| ASR | long final decoding uses chunks no longer than 19 seconds | unit | Pass |
| Engine | cadence thresholds and minimum interval are enforced | unit/fake clock | Pass |
| State | stable IDs and requirement-question links survive provider drift | unit | Pass |
| Overrides | edit/pin/dismiss/status changes survive later passes | unit/API | Pass |
| Mermaid | safe flowchart accepted; unsafe directives rejected | unit | Pass |
| Mermaid | common plain edge labels normalize to quoted safe labels | unit + local Ollama | Pass |
| Metrics | labels and numeric values are validated before rendering | unit/UI | Pass |
| TXT/paste | speaker labels and deterministic timestamps preserved | unit/API | Pass |
| VTT | Teams cue timestamps, multiline text, and speakers preserved | unit/API | Pass |
| DOCX import | paragraphs extracted without XML or empty content | unit/API | Pass |
| Upload safety | unsupported, oversized, binary, and unsafe ZIP rejected | unit/API security | Pass |
| Import isolation | import path does not construct microphone/ASR | integration | Pass |
| BRD Markdown | all sections and timestamped requirement evidence present | unit/API | Pass |
| BRD DOCX | headings, lists, tables, margins, header/footer, traceability | unit + structural QA | Pass |
| BRD DOCX | accessibility and table geometry audits | document QA tools | Pass |
| BRD DOCX | rendered page-image visual review | requires LibreOffice/Word UI | Pending external |
| Stories | epic/story generation, 2-5 ACs, traceability | unit/API | Pass |
| Stories | edits/deletions survive regeneration; merge retains evidence | unit/API | Pass |
| Jira | preview contains exact parent/child payloads without network call | unit/API | Pass |
| Jira | create parents first and persist returned keys | simulated Jira contract | Pass |
| Jira | re-export updates rather than duplicates | simulated Jira contract | Pass |
| Jira | auth/permission/validation/rate-limit errors are actionable | simulated Jira contract | Pass |
| Persistence | restart restores transcript, state, overrides, delivery mappings | integration | Pass |
| Offline bundle | source layout, model/wheel options, safe rebuild | unit/build smoke | Pass |
| Archive parts | split, checksums, reassembly, tamper rejection | unit | Pass |
| Diagnostics | required checks gate readiness; Jira remains optional | unit/live local | Pass |

## End-to-end gates

| ID | Scenario | Status |
|---|---|---|
| E2E-01 | Import 30-utterance workshop with local Ollama, then generate canvas, questions, BRD DOCX, epics, and stories | Pass |
| E2E-02 | Restart server and reopen the persisted imported session | Pass |
| E2E-03 | Run complete mock-provider workflow without cloud calls | Pass |
| E2E-04 | Start packaged Windows build from bundled wheels/models and pass diagnostics | Pass |
| E2E-05 | Grant browser microphone permission and speak a two-minute fixture discussion | Pending human |
| E2E-06 | Run launcher and microphone workflow on actual macOS hardware | Pending hardware |
| E2E-07 | Preview and sync to a real Jira project | Pending credentials |

## Current automated result

```text
114 passed, 1 skipped
```

The skipped test is the opt-in real-ASR fixture in the normal suite. It passed
when run with `REQPILOT_REAL_ASR_TEST=1` during the foundation verification.
