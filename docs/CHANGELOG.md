# CHANGELOG — ReqPilot

## 2026-07-16 — Local MVP shipped and verified
- Live mic pipeline: browser AudioWorklet capture → energy VAD → InkVoice-derived dual-model ASR (Zipformer partials + Parakeet punctuated finals, ≤19 s chunked decode). Human mic smoke (E2E-05) pending.
- Transcript import: paste / TXT / VTT (Teams) / DOCX with speaker + timestamp preservation.
- Intelligence: provider-pluggable (Groq/Anthropic/Ollama/mock) analysis → validated SessionState (summary, requirements, decisions, questions, diagrams, metrics, gaps) with stable IDs and durable analyst overrides; safe-subset Mermaid validation/normalization.
- Delivery: BRD (Markdown + styled DOCX) with timestamp evidence; epics/user stories with Gherkin ACs and traceability; Jira Cloud v3 preview + idempotent sync (contract-tested; real sync awaits credentials).
- Verification: 114 automated tests passed + 3 opt-in real-model ASR tests passed; independent live E2E on 2026-07-16 (import → local Ollama qwen3:8b analysis → canvas → BRD → stories) confirmed by main session.
- Known limitation observed: small local models can hallucinate quantitative values (metric peak invented in smoke test) — quantitative items should be verified against evidence utterances before use.

## 2026-07-16 — Project pivots and scope decisions
- ReqPilot defined (successor to paused TranslatorFlow); PRD v1.0→v1.2; renamed from dictation-typo "Ritu".
- Live-first mic-only scope (system-audio loopback deferred, workplace-prohibited); foundation = InkVoice engine port, not Meetily fork.
