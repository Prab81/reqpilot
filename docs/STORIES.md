# STORIES — ReqPilot

> Epics: E1 Capture · E2 Live Canvas · E3 Copilot · E4 Documents & Jira · E5 Platform
>
> **Build sequence (2026-07-16):**
> **M1 — Intelligence layer on transcripts** (no audio code): STORY-003, 004, 005, 008, 009, 011 — usable on the work laptop from day one
> **M2 — Live capture & real-time copilot** (Meetily fork): STORY-001, 002, 006, 007
> **M3 — Delivery integration & polish:** STORY-010, 012

---

### STORY-001: Live microphone capture (mic-only)
**Status:** In Progress
**Priority:** P0 (must)
**PRD Ref:** REQ-001, REQ-002 [REVISED — loopback deferred]
**Last Updated:** 2026-07-16

**As a** business analyst,
**I want** ReqPilot to capture the room through my microphone during a session,
**So that** in-room discussions are captured live without any meeting-recording software on the machine.

#### Acceptance Criteria
- [ ] AC1: [REVISED 2026-07-16] Mic captured continuously on Windows and macOS via browser (getUserMedia → 16 kHz PCM over WebSocket); system-audio loopback explicitly out of scope (workplace-prohibited), audio source pluggable for a future flagged loopback source
- [ ] AC2: [REVISED 2026-07-16] Single-channel (room) capture; channel abstraction preserved downstream for future sources
- [ ] AC3: Start/stop/pause controls; visible recording indicator
- [ ] AC4: Mic device selection in the browser; graceful error if permission denied or device busy

#### Technical Notes
Browser capture chosen over PortAudio/native (InkVoice M0 finding: PortAudio yields silence on Bluetooth LE Audio mics on Windows). Test scenarios TS-001-01..04.

#### Change History
- [2026-07-14] Created from REQ-001/002
- [2026-07-16] Sequenced to M2 — M1 ships the intelligence layer on transcripts first
- [2026-07-16] [REVISED] Live-first confirmed by Prabuddh; mic-only (loopback deferred, flagged); browser-capture approach; In Progress

---

### STORY-002: Real-time transcription with speaker attribution
**Status:** In Progress (2026-07-16)
**Priority:** P0 (must)
**PRD Ref:** REQ-004
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** a live scrolling transcript labeled by speaker (at minimum: me vs. them),
**So that** I can trust the capture and refer back during the meeting.

#### Acceptance Criteria
- [ ] AC1: Transcript appears ≤5s behind live speech (NREQ-001)
- [ ] AC2: Channel-level attribution (Analyst / Participants) in MVP
- [ ] AC3: Segments carry timestamps usable for traceability links (REQ-016)
- [ ] AC4: Works offline for transcription (local Whisper/Parakeet per Meetily)

#### Change History
- [2026-07-14] Created from REQ-004

---

### STORY-003: Transcript import mode
**Status:** Backlog
**Priority:** P0 (must) — [REVISED] was P1; promoted 2026-07-16: this is the primary work-laptop path and the M1 entry point
**PRD Ref:** REQ-003
**Last Updated:** 2026-07-16

**As a** business analyst,
**I want** to paste or upload an existing meeting transcript (Teams/Copilot export or any text),
**So that** ReqPilot can produce the canvas, document, questions, and stories for meetings it didn't attend — including work meetings where audio capture isn't possible.

#### Acceptance Criteria
- [ ] AC1: [REVISED 2026-07-16] txt, vtt (Teams transcript export), docx, and raw copy-pasted Copilot/Teams recap text accepted; speaker labels preserved when present
- [ ] AC2: Full pipeline (canvas, copilot questions, BRD, stories) runs over imported text
- [ ] AC3: Import of a 2-hour transcript completes in under 3 minutes
- [ ] AC4: Works with zero audio-capture components installed (NREQ-007 corporate-device mode)

#### Change History
- [2026-07-14] Created from REQ-003
- [2026-07-16] [REVISED] Promoted P1→P0; Teams/Copilot formats made explicit; AC4 added — Prabuddh confirmed personal-use build with work-laptop deployment where transcript import is the only sanctioned input

---

### STORY-004: Live one-pager canvas
**Status:** In Progress (2026-07-16)
**Priority:** P0 (must)
**PRD Ref:** REQ-005, REQ-007, REQ-008
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** a continuously updating one-pager (summary, requirements so far, decisions, open points),
**So that** the room sees a shared, current picture of the discussion and can correct it live.

#### Acceptance Criteria
- [ ] AC1: Canvas refreshes incrementally ≤60s after new content; no full-page flicker
- [ ] AC2: Sections: Summary · Requirements captured · Decisions · Open questions
- [ ] AC3: Presentable layout suitable for screen-sharing (REQ-007)
- [ ] AC4: Pin / edit / dismiss any element without stopping capture (REQ-008)
- [ ] AC5: Edits are never overwritten by subsequent auto-updates

#### Technical Notes
Incremental LLM pass over a rolling transcript window + running state object; render diff-patches, not full regenerations.

#### Change History
- [2026-07-14] Created from REQ-005/007/008

---

### STORY-005: Auto-generated visuals (flows, process maps, charts)
**Status:** In Progress (2026-07-16)
**Priority:** P0 (must)
**PRD Ref:** REQ-006
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** ReqPilot to choose and render the right visual for what's being described — flow diagram for a process, chart for numbers, table/bullets otherwise,
**So that** the discussion is mirrored visually without me drawing anything.

#### Acceptance Criteria
- [ ] AC1: Process descriptions render as Mermaid flowcharts/process maps on the canvas
- [ ] AC2: Quantitative statements (volumes, splits, trends) render as simple charts
- [ ] AC3: Visuals update as the description evolves (a step added in conversation appears in the diagram)
- [ ] AC4: A malformed/failed diagram degrades to bullets — never a broken render on screen

#### Change History
- [2026-07-14] Created from REQ-006

---

### STORY-006: Copilot question panel
**Status:** In Progress (2026-07-16)
**Priority:** P0 (must) — this is the differentiator
**PRD Ref:** REQ-009, REQ-012
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** suggested clarifying questions per detected requirement, live in a side panel,
**So that** I ask the right substantiating questions while the stakeholder is still in the room.

#### Acceptance Criteria
- [ ] AC1: New requirement detected → 2–5 targeted questions appear within 60s (who/when/volumes/exceptions/data/acceptance)
- [ ] AC2: Questions are specific to the stated requirement, not generic boilerplate
- [ ] AC3: Mark asked / answered / parked; answered ones disappear from the queue and feed the BRD (REQ-012)
- [ ] AC4: Panel is glanceable — analyst reads a question in ≤5 seconds

#### Change History
- [2026-07-14] Created from REQ-009/012

---

### STORY-007: Gap and conflict detection
**Status:** Backlog
**Priority:** P1 (should)
**PRD Ref:** REQ-010, REQ-011
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** ReqPilot to flag missing actors, undefined terms, unstated NFRs, unhandled edge cases, and contradictions with earlier statements,
**So that** gaps surface during the meeting instead of during UAT.

#### Acceptance Criteria
- [ ] AC1: Gap categories covered: actors, definitions, NFRs (perf/security/compliance), error/edge cases
- [ ] AC2: Contradiction flags cite both conflicting transcript segments
- [ ] AC3: False-positive control: flags are dismissible and dismissed patterns are not re-raised in-session

#### Change History
- [2026-07-14] Created from REQ-010/011

---

### STORY-008: Parallel BRD document builder
**Status:** In Progress (2026-07-16) — scope this phase: BRD generated on session stop; DOCX export deferred (markdown first)
**Priority:** P0 (must)
**PRD Ref:** REQ-013, REQ-016
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** a detailed free-form BRD assembling itself in the background during the session,
**So that** I leave the meeting with a near-complete draft instead of hours of writing.

#### Acceptance Criteria
- [ ] AC1: Document grows continuously; viewable anytime during the session
- [ ] AC2: Sections: context, stakeholders, current/future process, functional requirements, NFRs, assumptions, open items
- [ ] AC3: Each requirement links to its source transcript timestamp (REQ-016)
- [ ] AC4: Export as Markdown and DOCX

#### Change History
- [2026-07-14] Created from REQ-013/016

---

### STORY-009: Epics & user-story generation
**Status:** Backlog
**Priority:** P0 (must)
**PRD Ref:** REQ-014
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** ReqPilot to decompose captured requirements into epics and user stories with acceptance criteria,
**So that** delivery-ready artifacts exist minutes after the workshop ends.

#### Acceptance Criteria
- [ ] AC1: Standard story format ("As a / I want / So that") with 2–5 testable ACs each
- [ ] AC2: Stories grouped under epics; every story traces to a requirement and transcript segment
- [ ] AC3: Analyst can edit/merge/delete before export; regeneration respects edits

#### Change History
- [2026-07-14] Created from REQ-014

---

### STORY-010: Jira export
**Status:** Backlog
**Priority:** P0 (must)
**PRD Ref:** REQ-015
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** one-click export of approved epics/stories into a Jira project,
**So that** requirements flow straight into the delivery backlog.

#### Acceptance Criteria
- [ ] AC1: Creates Epic and Story issue types with correct epic-links in the target project
- [ ] AC2: ACs land in the description (or AC field where configured); ReqPilot session URL/reference included
- [ ] AC3: Idempotent re-export — re-running updates rather than duplicates
- [ ] AC4: Clear error surface for auth/permission failures

#### Change History
- [2026-07-14] Created from REQ-015

---

### STORY-011: Session persistence & workspace
**Status:** In Progress (2026-07-16) — minimal scope this phase: auto-save + reopen; crash-recovery AC deferred to hardening
**Priority:** P0 (must)
**PRD Ref:** REQ-017
**Last Updated:** 2026-07-14

**As a** business analyst,
**I want** sessions saved locally and reopenable with full state (transcript, canvas, doc, questions),
**So that** nothing from a client workshop is ever lost.

#### Acceptance Criteria
- [ ] AC1: Auto-save during session; crash-recovery restores to within the last 30s
- [ ] AC2: Session list with title, date, duration; reopen restores all four surfaces
- [ ] AC3: All data stored locally (NREQ-003)

#### Change History
- [2026-07-14] Created from REQ-017

---

### STORY-012: Template packs & tailored document structures
**Status:** Backlog
**Priority:** P2 (nice to have — Release 2)
**PRD Ref:** Release 2 section
**Last Updated:** 2026-07-14

**As a** consulting BA,
**I want** to load my organisation's document template so ReqPilot elicits and fills that structure,
**So that** output matches house standards without rework.

#### Change History
- [2026-07-14] Created as Release-2 placeholder per PRD
