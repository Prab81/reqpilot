# ReqPilot delivery stories

Status reflects the build on 2026-07-16. “Implemented” means code and automated
coverage exist; the external verification notes identify checks that require
hardware or credentials unavailable to the build session.

## STORY-001 - Live microphone capture

**Status:** Done (code + automated tests); physical-mic smoke pending — E2E-05 requires a human to grant browser mic permission and speak
**Priority:** P0

As a business analyst, I want to capture an in-room workshop through the
computer microphone so that the discussion is available to the live copilot.

- [x] Browser `getUserMedia` capture and 16 kHz PCM WebSocket transport.
- [x] Single room channel with a pluggable audio-source boundary.
- [x] Start, stop, pause, resume, recording indicator, and device selector.
- [x] Clear permission/device errors without making the rest of the app unusable.
- [ ] Human smoke test with the actual microphone and browser permission.

## STORY-002 - Real-time transcription

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want a timestamped live transcript so that I can trust
the capture and trace requirements to what was said.

- [x] Streaming partial text and punctuated final utterances.
- [x] Session-relative timestamps and ordered identifiers.
- [x] Local/offline Zipformer and Parakeet models.
- [x] Long utterances segmented and decoded in chunks no longer than 19 seconds.

Speaker diarization is not claimed for the single microphone channel; imported
speaker labels are preserved.

## STORY-003 - Transcript import

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want to paste or upload a prior meeting transcript so
that ReqPilot works for meetings it did not attend.

- [x] TXT, Teams VTT, DOCX, and pasted text accepted.
- [x] Speaker labels and supplied timestamps preserved.
- [x] Canvas, questions, BRD, and story pipeline runs after import.
- [x] Import path does not construct microphone or ASR components.
- [x] Size, path, binary, archive, and malformed-input safeguards.

## STORY-004 - Live one-page canvas

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want a continuously updated summary, requirements,
decisions, and open points so the room can share and correct the current view.

- [x] Incremental state updates without page reload.
- [x] Summary, requirements, decisions, questions, gaps, diagrams, and metrics.
- [x] Responsive screen-shareable layout.
- [x] Pin, edit, dismiss, and question-status controls.
- [x] Overrides survive later model passes and server restart.

## STORY-005 - Auto-generated visuals

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want processes and quantities rendered visually so
that I do not need to draw while facilitating.

- [x] Safe Mermaid flowcharts/process maps.
- [x] Bar and pie metric rendering with accessible text fallbacks.
- [x] Visuals are regenerated from evolving state.
- [x] Invalid Mermaid is dropped with an elicitation gap, never rendered broken.

## STORY-006 - Copilot questions

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want targeted clarifying questions so I can close gaps
while stakeholders are present.

- [x] Requirement-linked questions across actors, data, volumes, exceptions,
  NFRs, and acceptance criteria.
- [x] Specific prompts are generated from the session state and evidence.
- [x] Asked, answered, and parked states persist.
- [x] Suggested-question queue is glanceable and keyboard accessible.

## STORY-007 - Gap and conflict detection

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P1

As a business analyst, I want missing information and contradictions surfaced
during elicitation so they do not wait until UAT.

- [x] Actor, definition, NFR, edge-case, and conflict categories.
- [x] Evidence utterance references retained for conflicts.
- [x] Dismissed flags are suppressed from later passes.

## STORY-008 - BRD document builder

**Status:** Done — BRD verified live 2026-07-16 (all sections + 11 timestamp evidence refs); DOCX visual page-render review pending (needs Word/LibreOffice eyes)
**Priority:** P0

As a business analyst, I want a traceable BRD ready after the meeting so that I
avoid hours of manual drafting.

- [x] BRD can be refreshed and viewed at any time after state exists.
- [x] Context, stakeholders, current/future process, functional requirements,
  NFRs, assumptions, decisions, and open items.
- [x] Requirement-to-transcript timestamps.
- [x] Markdown and styled DOCX export.
- [x] DOCX structural, geometry, heading, and accessibility QA.
- [ ] Page-image render on a machine with LibreOffice or reliable Word automation.

## STORY-009 - Epics and user stories

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want delivery-ready epics and stories so the workshop
output can move directly into refinement.

- [x] As-a/I-want/So-that format with 2-5 acceptance criteria.
- [x] Epic grouping and requirement/transcript traceability.
- [x] Edit, merge, and delete controls.
- [x] Regeneration preserves edits and suppresses deletions.

## STORY-010 - Jira export

**Status:** Done (simulated-Jira contract tests: create/idempotent-update/error paths); real-site sync pending Jira credentials (E2E-07)
**Priority:** P0

As a business analyst, I want approved epics and stories synchronized to Jira
so that they enter the delivery backlog without re-keying.

- [x] Jira Cloud v3 Epic and Story payloads with parent relationships.
- [x] Acceptance criteria and ReqPilot traceability in descriptions.
- [x] Idempotent update of stored Jira keys.
- [x] Actionable authentication, permission, validation, and rate-limit errors.
- [x] Preview and status endpoints never expose tokens.
- [ ] Real export using the user's Jira site, token, and project.

## STORY-011 - Session persistence

**Status:** Done — automated suite green; independently verified live 2026-07-16 (import → Ollama analysis → canvas → BRD → stories)
**Priority:** P0

As a business analyst, I want sessions saved locally and reopenable so that
meeting output is not lost.

- [x] Transcript appends and atomic state/delivery snapshots.
- [x] Session list and restoration of transcript, canvas, BRD, and stories.
- [x] Configurable local data directory.
- [x] Analysis watermark and ID high-water recovery after restart.

## STORY-012 - Template packs

**Status:** Deferred to release 2
**Priority:** P2

Organisation-specific document templates remain an intentional extension point.
The current business-brief DOCX style provides the common default structure.
