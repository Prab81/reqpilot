# CONTEXT — ReqPilot (append-only decision log)

## [2026-07-14] — Project bootstrapped: ReqPilot, requirements-elicitation copilot
**Type:** Scope Change
**Impact:** High

### Context
Successor product to the paused TranslatorFlow (see V:/AI/TranslatorFlow/docs/CONTEXT.md,
entry "Build paused pending strategic (moat) decision"). That research concluded a
horizontal consumer translation app had no moat and recommended a vertical workflow
product instead. Prabuddh defined ReqPilot: a real-time copilot for business analysts
that listens to requirements meetings, renders a live visual one-pager, prompts
clarifying questions, builds the detailed document in parallel, and spins out
epics/stories to Jira.

### Decision / Finding
PRD v1.0 drafted (docs/PRD.md), STORY-001..012 created. MVP: desktop app, dual-channel
audio capture or transcript import, live canvas with auto-visuals, copilot question
panel, free-form BRD, story generation + Jira export. Template packs, meeting bots, and
multi-session memory deferred to Release 2.

### Rationale
Competitive scan (docs/COMPETITIVE_LANDSCAPE.md) found no product combining live
listening + live visuals + elicitation prompting + stories-to-Jira. Closest: Hedy
(generic live coaching), BA Copilot (transcript→BPMN, not live), Copilot4DevOps
(written-requirements QA). Vertical methodology depth + workflow integration is the moat
the translation product lacked.

### Implications
Reuses the live-audio→STT→LLM pipeline knowledge from TranslatorFlow. PRD Status is
Draft until Prabuddh approves scope and the open questions (stakeholder view, diarization
depth, Jira auth path, naming).

---

## [2026-07-14] — Foundation: fork Meetily rather than build capture from scratch
**Type:** Decision
**Impact:** High

### Context
Prabuddh asked whether a highly-rated, safe open-source repo exists to build upon.
Hardest MVP plumbing is Windows/macOS system-audio loopback capture + real-time local
transcription.

### Decision / Finding
Build on **Meetily** (github.com/Zackriya-Solutions/meetily): MIT, 24.4k stars, active
(v0.4.0 Jun 2026), Rust/Tauri core with dual-channel mic+system-audio capture, local
Whisper/Parakeet real-time STT with GPU accel, Next.js frontend, pluggable LLM providers
including Groq (key already in hand). Approach: fork; keep the ReqPilot intelligence
layer (canvas, copilot, BRD, stories/Jira) in a cleanly separated module so the upstream
capture core can be rebased.

### Rationale
- Alternatives rejected: **Amurex** (concept twin for real-time suggestions but stale
  ~16 months, AGPL-3.0 viral license, Chrome-extension capture misses in-room meetings —
  study its UX only); **Hyprnote/Anarlog** (good, MIT, but Windows support lagged
  Meetily's as of early 2026); **build from scratch** (4–6 weeks of audio plumbing for
  zero differentiation).
- MIT permits commercial use without copyleft obligations.
- Risk noted: Meetily vendor now sells a PRO tier — OSS core direction could narrow;
  fork isolates us from upstream strategy changes.

### Implications
MVP architecture inherits Tauri (Rust) + Next.js. ReqPilot-layer work is LLM
orchestration and UI — no audio engineering. ARCHITECTURE.md to be written when
implementation starts.

---

## [2026-07-14] — Product renamed: "Ritu" → "ReqPilot"
**Type:** Decision
**Impact:** Low

### Context
"Ritu" in the original product brief was a dictation-software artifact, not an intended
name. Prabuddh asked for a suitable replacement.

### Decision / Finding
Working name **ReqPilot** (requirements + copilot). Web scan found no existing product
with this name; nearest neighbours are ReqIt.AI and Copilot4DevOps's "Elicit" feature.
Project folder, PRD, stories, and memory all renamed. Formal domain/trademark check
remains an Open Question in the PRD.

---

## [2026-07-14] — Second-pass moat assessment: build gated on dogfooding
**Type:** Discovery
**Impact:** High

### Context
Prabuddh asked whether ReqPilot is itself weak-moat (like TranslatorFlow) and whether
using existing tools/open source would be smarter than building.

### Decision / Finding
Assessment delivered: moat is **moderate at best as a horizontal "BA copilot" SaaS**.
Primary threat is platform absorption, not startups — Microsoft Teams Copilot (in-meeting
transcript + Q&A) and Atlassian Rovo (content → epics/stories) squeeze the pipeline from
both ends for enterprise users. The differentiated middle (live canvas, methodology-aware
elicitation, traceability) is real but replicable — defensibility is not in the tech.
Structural niche that survives: consultants/agency BAs who cannot install bots or Copilot
in client tenants — device-side capture (Meetily architecture) works in any client
meeting. Known adoption risk: recording-consent/confidentiality friction for device-side
capture; local-first processing mitigates but does not remove it.

Recommended path (decision pending Prabuddh):
1. Do NOT start product build. Dogfood first: Meetily + Claude prompt pack (gaps,
   questions, BRD, stories) + Jira MCP on real requirements meetings (~70% of output
   value, zero engineering).
2. Build the live layer (canvas + in-meeting question prompts) on the Meetily fork ONLY
   if dogfooding shows the in-meeting moment is where the value concentrates.
3. If productized, go narrow: consultants/agencies (BYO niche) or a single domain
   (e.g., ERP, insurance) with deep template/question-bank packs — not horizontal.

### Implications
STORY-001..012 remain Backlog; PRD stays Draft. Next concrete step if Prabuddh agrees:
set up the dogfood stack (Meetily install + prompt pack + Jira MCP wiring).

---

## [2026-07-16] — Scope confirmed: build-to-use; milestone order inverted (transcripts first)
**Type:** Scope Change
**Impact:** High

### Context
Prabuddh confirmed he wants to build ReqPilot — primarily for his own use, eventually
running on his work laptop alongside (never inside) Microsoft Teams. Work meetings offer
Teams/Copilot transcript exports; in-room workshops offer live mic audio. A trading-
product moonshot exploration (deep research run) was parked the same day.

### Decision / Finding
PRD bumped to v1.1. Three changes:
1. **Build-to-use:** personal tool first; commercialization deferred (moat assessment
   from 2026-07-14 stands).
2. **Teams strategy — beside, not inside:** no Teams app/plugin (corporate tenant won't
   allow it). Work path = transcript import (Teams .vtt / Copilot recap paste, post-
   meeting); live-copilot value comes from in-room mic capture and personal-device
   meetings. Live Teams-call access via Graph API rejected: requires tenant-admin
   consent Prabuddh won't get.
3. **Milestones inverted — intelligence layer first:** M1 = full pipeline over imported
   transcripts (canvas + visuals + questions report + BRD + stories) with zero audio
   code; M2 = live capture via Meetily fork (real-time canvas + question prompts);
   M3 = Jira export + template packs. STORY-003 promoted P1→P0; NREQ-007 added
   (corporate-device mode: no-capture operation + local-only inference option).

### Rationale
The intelligence layer is identical across input modes and is the actual product; it is
usable at work immediately (where audio capture may be prohibited), requires no Rust/
audio engineering, and validates output quality before the live layer is built. The
live in-room experience (M2) remains the differentiator and the reason the desktop app
exists at all.

### Implications
M1 need not be the Meetily fork — a lightweight local app is enough; the Meetily fork
decision applies from M2. Architecture choice (extend Meetily's Next.js frontend from
day one vs. standalone M1 app merged later) is the first implementation decision.
Work-laptop deployment blocked on one open question: employer IT policy on installs,
audio capture, and cloud LLM use for meeting content.

---

## [2026-07-16] — Build started: live-first, mic-only, on the InkVoice engine (not Meetily)
**Type:** Decision
**Impact:** High

### Context
Prabuddh reprioritized: build the live experience first ("I want to see how that can
be made to work"), mic-only — system-audio loopback excluded as workplace-prohibited
(mic-only fully covers in-room workshops; remote-meeting others' audio is unreachable
by mic when on headphones — transcript import covers that case later). Windows + macOS.
He directed reuse of the InkVoice (Netriq InkVoice) Parakeet pipeline.

### Decision / Finding
1. **Foundation switch: InkVoice engine port replaces the Meetily fork** for this
   phase. InkVoice's sidecar (V:/AI/Netriq InkVoice/dist/InkVoice/sidecar/asr_server.py)
   provides a proven dual-model sherpa-onnx pipeline: Parakeet-TDT-0.6b-v3 int8 for
   punctuated finals + streaming Zipformer for stable live partials, including the
   chunked ≤19 s decode fix for the >20 s Parakeet degradation. Pure Python, macOS
   arm64 wheels exist, both model sets already on disk. Meetily stays as reference
   for the future loopback source only.
2. **Mic capture in the browser** (getUserMedia → AudioWorklet → 16 kHz PCM over
   WebSocket), not PortAudio/native: InkVoice's M0 finding (PortAudio silence on
   Bluetooth LE Audio mics on Windows) is dodged entirely; Win+Mac parity free;
   permission UX handled by the browser. Audio source is pluggable (future flagged
   loopback per revised REQ-002).
3. **Stack:** Python 3.14 + FastAPI/uvicorn server, browser UI (three panes:
   transcript / canvas with Mermaid+charts / copilot questions), LLM provider
   interface Groq (default) | Anthropic | Ollama | Mock. Full contracts in
   ARCHITECTURE.md (build authority); TEST_SCENARIOS.md populated up front per
   Prabuddh's instruction (testing at every stage).
4. **Execution model:** parallel sub-agent tracks (A: audio/ASR+server, B:
   intelligence+persistence, C: frontend) per Prabuddh's instruction; integration
   and end-to-end verification in the main session.

### Implications
Phase order now: Phase-Live (this build) → Phase-Transcript (import; reuses everything
but the audio path) → Phase-Delivery (stories/Jira). PRD v1.2 Approved. Stories
001/002/004/005/006/008/011 In Progress. macOS validation (TS-E2E-03) deferred until
Mac access.

---
