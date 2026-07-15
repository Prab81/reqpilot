# TEST SCENARIOS — ReqPilot Phase-Live

> Status: Pending = defined, not yet runnable · Ready = implementation exists, scenario executable · Pass/Fail = last run result.
> Unit/integration tests live in tests/ (pytest). Scenario IDs referenced from story ACs.

## STORY-001 / REQ-001 — Mic capture (browser)
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-001-01 | Grant mic permission → start session → PCM frames arrive at server (rate ≈16 kHz, float32, non-silent RMS) | Live smoke (browser) | Ready |
| TS-001-02 | Deny mic permission → clear error banner, no WS audio, app usable for viewing sessions | Live smoke | Ready |
| TS-001-03 | Pause/resume capture → no frames while paused; resume continues same session | Live smoke | Ready |
| TS-001-04 | Downsampler: 48 kHz sine → 16 kHz output preserves frequency, no aliasing artifacts above Nyquist | Unit (JS logic mirrored in pytest fixture) | Ready |

## STORY-002 / REQ-004 — Live transcription
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-002-01 | Feed fixture WAV (short utterance) through AsrEngine → exactly one final; text matches expected phrase (fuzzy ≥0.8) | Integration (pytest, real models) | Ready |
| TS-002-02 | Two utterances separated by 1.5 s silence → two finals with correct ordering and t0/t1 gaps | Integration | Ready |
| TS-002-03 | Partials stream while speaking: ≥1 partial before final for a ≥3 s utterance | Integration | Ready |
| TS-002-04 | 50 s continuous speech → forced segmentation ≤45 s; no dropped audio between segments (concatenated text covers content) | Integration | Ready |
| TS-002-05 | VAD unit: silence→speech→silence produces one segment incl. 300 ms pre-roll; hangover keeps mid-sentence 500 ms pauses inside one segment | Unit | Ready |
| TS-002-06 | Decoder chunking: 30 s utterance decodes in ≥2 chunks, all ≤19 s (InkVoice >20 s degradation guard) | Unit | Ready |

## STORY-004 / REQ-005,007,008 — Live canvas
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-004-01 | MockProvider returns state with summary+requirements → canvas renders all sections; rev increments | Integration (server) + live smoke | Ready |
| TS-004-02 | Second engine pass preserves IDs of unchanged items (R1 stays R1) | Unit (engine) | Ready |
| TS-004-03 | User dismisses a requirement → next engine pass does NOT resurrect it (override re-applied) | Unit (server overrides) | Ready |
| TS-004-04 | User edit of item text survives subsequent passes | Unit | Ready |
| TS-004-05 | Engine cadence: passes triggered by content threshold, never <15 s apart | Unit (fake clock) | Ready |

## STORY-005 / REQ-006 — Auto visuals
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-005-01 | State with valid Mermaid flowchart → rendered SVG appears on canvas | Live smoke | Ready |
| TS-005-02 | Invalid Mermaid from LLM → item dropped server-side with gap note; client never receives broken diagram | Unit (validator) | Ready |
| TS-005-03 | Metrics item (bar) renders a chart with matching labels/values | Live smoke | Ready |
| TS-005-04 | Process description in fixture transcript → engine (MockProvider replay of real Groq response) produces flowchart whose nodes cover the described steps | Integration | Ready |

## STORY-006 / REQ-009,012 — Copilot question panel
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-006-01 | New requirement in pass → 2–5 questions with category + requirement link | Unit (engine w/ mock) | Ready |
| TS-006-02 | Mark question asked/answered/parked via override API → status persists across passes | Unit | Ready |
| TS-006-03 | Answered questions leave the suggested queue in UI | Live smoke | Ready |

## STORY-008 / REQ-013,016 — BRD generation (post-session, this phase: on stop)
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-008-01 | POST /brd on a session with fixture state → markdown contains all BRD sections + every requirement with utterance evidence refs | Unit (mock) | Ready |
| TS-008-02 | BRD requirement lines cite utterance timestamps that exist in the session log | Unit | Ready |

## STORY-011 / REQ-017 — Session persistence
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-011-01 | Kill server mid-session → restart → session listed; transcript + last state snapshot restored | Integration | Ready |
| TS-011-02 | All session artifacts under local data dir; nothing written outside project data dir | Unit | Ready |

## End-to-end (Phase-Live exit criteria)
| ID | Scenario | Type | Status |
|----|----------|------|--------|
| TS-E2E-01 | Speak a 2-min scripted requirements discussion into the mic → live partials visible; canvas shows ≥1 requirement, ≥1 question, ≥1 diagram; stop → BRD downloads | Live smoke (manual script in tests/fixtures/e2e_script.md) | Ready |
| TS-E2E-02 | Same flow with REQPILOT_PROVIDER=mock → full pipeline works offline (no API key) | Integration | Ready |
| TS-E2E-03 | macOS run: run_mac.sh boots, models load, TS-E2E-02 passes | Manual (deferred until Mac access) | Pending |
