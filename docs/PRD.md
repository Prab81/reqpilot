# PRD: ReqPilot — Real-Time Requirements Elicitation Copilot
**Version:** 1.2
**Last Updated:** 2026-07-16
**Status:** Approved (Phase-Live scope confirmed by Prabuddh 2026-07-16)

## Problem Statement
Business analysts run requirements workshops and stakeholder meetings where three jobs
compete for their attention: (1) listening and facilitating, (2) capturing what was said
accurately, and (3) noticing what was NOT said — gaps, ambiguities, unasked questions.
Today the BA does all three manually, then spends hours afterwards writing the BRD,
drawing process maps, and decomposing requirements into epics/stories. Existing AI
note-takers (Granola, Otter, Fireflies) summarize *after* the meeting and are generic —
none drive the *elicitation* itself, none render live visuals, and none understand
requirements methodology.

ReqPilot listens to the meeting live and acts as a true co-pilot for the analyst:
capturing, structuring, visualizing, and — critically — prompting the analyst with the
right clarifying questions *while the stakeholder is still in the room*.

## Goals
- [ ] G1: Capture meeting audio live (analyst mic + other participants' audio) or ingest a transcript
- [ ] G2: Live one-pager canvas — running summary, captured requirements, decisions, open points — updating as the discussion happens
- [ ] G3: Auto-generated visuals on the canvas where content warrants: flow diagrams, process maps, simple charts, structured bullets
- [ ] G4: Copilot panel — clarifying questions, detected gaps, and coverage prompts surfaced in real time for the analyst to ask
- [ ] G5: Parallel detailed elicitation document (free-form BRD in MVP) built continuously in the background
- [ ] G6: Post-session: generate epics and user stories with acceptance criteria, exportable to Jira
- [ ] G7: Everything traceable — each requirement/question links back to the transcript moment that produced it

## Non-Goals (MVP)
- Meeting-bot that joins Zoom/Teams/Meet calls as a participant (capture is device-side: mic + system-audio loopback covers remote meetings played through the machine)
- Embedding inside Microsoft Teams as an app/plugin — corporate tenants won't permit it; ReqPilot runs *beside* Teams (transcript import or room-mic capture), never inside it
- Organisation-specific document templates (MVP is free-form BRD; template packs are Release 2)
- Multi-language (English first)
- Mobile apps, SSO/enterprise admin, multi-tenant SaaS (MVP is a desktop app for one analyst)
- Perfect speaker diarization (best-effort labels; analyst can correct)

## Release 2+ (documented, not in scope now)
- Template packs: BRD formats, use-case specs, agile discovery canvases; org-tailorable
- Meeting-platform bots and calendar integration
- Multi-session project memory (requirements accumulate across workshops, cross-meeting traceability)
- Pre-meeting mode: generate agenda + question bank from prior docs; track coverage live
- Requirement quality scoring (ambiguity/testability flags per INVEST & BABOK heuristics)
- Confluence publishing; requirements traceability matrix

## User Personas
- **Business Analyst (primary):** runs elicitation workshops; needs to stay present in the conversation while capture and gap-spotting happen automatically.
- **Product Owner / Consultant:** same workflow, lighter methodology; wants the one-pager to share at meeting end and stories in Jira by end of day.
- **Business Stakeholder (indirect):** sees the live canvas projected in the room; confirms "yes, that's what I meant" in the moment.

## Requirements

### Functional — Capture
- REQ-001: Capture microphone audio (analyst / in-room) continuously during a session
- REQ-002: [REVISED 2026-07-16 — deferred to a later release, behind a feature flag] System-audio loopback capture is workplace-prohibited; audio input is designed as a pluggable source so loopback can be added later without downstream changes. Original: capture system audio simultaneously with mic as separate channels.
- REQ-003: Accept a pasted/uploaded transcript as a first-class input and run the full pipeline over it — formats: txt, vtt (Microsoft Teams transcript export), docx, and copy-pasted Copilot/Teams recap text with speaker labels preserved
- REQ-004: Real-time transcription with speaker attribution (best-effort), visible as a scrolling transcript

### Functional — Live Canvas (real-time display)
- REQ-005: One-pager canvas updates continuously (≤60s lag) with: session summary bullets, requirements captured so far, decisions made, open questions
- REQ-006: Auto-select and render the right representation per content: flow diagram / process map (Mermaid or equivalent) for processes, simple charts for quantitative statements, bullets/tables otherwise
- REQ-007: Canvas is presentable — clean enough to screen-share or project during the meeting
- REQ-008: Analyst can pin, edit, or dismiss any canvas element without stopping capture

### Functional — Copilot (the differentiator)
- REQ-009: For each requirement detected, surface suggested clarifying questions (who/when/volume/exceptions/data/acceptance) in a side panel in near-real-time
- REQ-010: Detect and flag gaps: missing actors, undefined terms, unstated NFRs (performance, security, compliance), unhandled error/edge cases
- REQ-011: Detect contradictions/conflicts with earlier statements in the session and flag them
- REQ-012: Analyst can mark a suggested question as asked/answered/parked; answered questions feed back into the document

### Functional — Documents & Output
- REQ-013: Build a detailed free-form elicitation document (BRD-style) in parallel throughout the session; exportable as Markdown and DOCX
- REQ-014: On demand or at session end, generate epics and user stories (standard "As a… I want… So that…" + acceptance criteria) from captured requirements
- REQ-015: Export epics/stories to Jira (create issues with correct type, links epic→story) via Jira API/MCP
- REQ-016: Every requirement, question, and story carries a link to its source transcript segment (timestamp)
- REQ-017: Sessions persist locally; reopening a session restores transcript, canvas, document, and copilot state

### Non-Functional
- NREQ-001: Transcription latency ≤5s behind live speech; canvas/copilot refresh ≤60s
- NREQ-002: Runs on Windows and macOS desktop
- NREQ-003: Transcript audio processed locally where feasible (client confidentiality); LLM calls to cloud allowed but configurable/pluggable per provider
- NREQ-004: LLM + STT providers behind interfaces (Groq/Claude/local Ollama swappable)
- NREQ-005: A 2-hour workshop costs ≤ $1 in inference at MVP volumes
- NREQ-006: API keys via .env / OS keychain, never committed
- NREQ-007: Corporate-device mode — transcript-import path must work with zero audio capture and offer a local-only inference option (Ollama) so confidential work content never leaves the machine; installation footprint must suit a managed laptop (portable build or browser-served UI), subject to employer IT policy

## Open Questions
- [ ] Employer IT policy: is installing/running audio-capture software on the work laptop permitted? Is cloud LLM use permitted for meeting content, or is local-only (Ollama) required at work? (owner: Prabuddh)
- [ ] Canvas projection: is "screen-share the canvas" enough for MVP, or is a separate read-only stakeholder view needed? (owner: Prabuddh)
- [ ] Diarization depth for MVP: channel-level (mic vs system) only, or per-speaker within a channel?
- [ ] Jira export: direct REST with user token vs. Atlassian MCP already connected to this environment?
- [ ] Name/brand check: "ReqPilot" domain/trademark availability — initial web scan 2026-07-14 found no product collisions (nearest names: ReqIt.AI, Copilot4DevOps "Elicit").

## Decisions Made
- [2026-07-14] Build on Meetily (MIT) for capture + local transcription; ReqPilot's intelligence layer (canvas, copilot, doc/story generation) is our own code. Rationale: see docs/CONTEXT.md and docs/COMPETITIVE_LANDSCAPE.md.
- [2026-07-14] MVP is a local-first desktop app (Tauri), not a SaaS. Rationale: reuses Meetily's architecture; client-confidential audio stays on device; fastest path to a usable tool.
- [2026-07-14] MVP document format is free-form BRD; org-specific templates deferred to Release 2 (per Prabuddh's framing).
- [2026-07-14] Working name "ReqPilot" ("Ritu" was a dictation artifact, discarded).
- [2026-07-16] **Build-to-use:** ReqPilot is being built as Prabuddh's personal tool first; commercialization deferred indefinitely (moat assessment stands — see CONTEXT.md).
- [2026-07-16] **Teams strategy — beside, not inside:** no Teams app/plugin. Work-meeting path is Teams/Copilot transcript import (post-meeting); live copilot value comes from in-room mic capture and personal-device meetings.
- [2026-07-16] **Milestone order inverted — intelligence layer first:** M1 = transcript-import pipeline (canvas, visuals, questions report, BRD, stories) with no audio code; M2 = live capture (Meetily fork) enabling the real-time copilot; M3 = Jira export + polish. Rationale: the intelligence layer is identical across input modes, usable at work immediately, and validates the product before any audio engineering. **[SUPERSEDED same day — see next decision]**
- [2026-07-16] **Live-first, mic-only (Prabuddh's call):** Phase-Live ships first — live mic capture (no system-audio loopback; workplace-prohibited), Windows + macOS, live canvas + copilot + post-session BRD. Phase-Transcript (import mode) second, Phase-Delivery (epics/stories refinement + Jira) third. Audio input built as a pluggable source so loopback can be flag-added later.
- [2026-07-16] **Foundation revised — InkVoice engine, not a Meetily fork:** ReqPilot ports InkVoice's proven sherpa-onnx dual-model ASR (Parakeet-TDT-0.6b-v3 int8 finals with punctuation/casing + streaming Zipformer live partials, chunked-decode fix for >20s utterances) — pure Python, macOS wheels available, models already on disk. Mic capture happens in the browser (getUserMedia → WebSocket PCM), avoiding InkVoice's PortAudio/Bluetooth-LE-Audio capture failure and giving Win+Mac parity with zero native audio code. Meetily remains the reference implementation for the future loopback source only.
