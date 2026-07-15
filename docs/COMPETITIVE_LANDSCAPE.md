# Competitive Landscape — ReqPilot (researched 2026-07-14)

## The whitespace
Nobody found combines all four of ReqPilot's pillars in one product:
**live listening → live visual one-pager → real-time elicitation prompts → epics/stories to Jira.**
Each pillar exists somewhere; the combination — a methodology-aware copilot that *drives*
elicitation during the meeting — does not.

## Category 1 — AI meeting note-takers (post-meeting, generic)
| Product | What it does | Gap vs ReqPilot |
|---|---|---|
| Granola | Device-audio notes, no bot, Mac/iOS-first | Post-meeting summary only; no visuals, no elicitation, no Jira |
| Otter.ai | Live transcript on screen, post-meeting summary | Live transcript ≠ live intelligence; generic |
| Fireflies | 100+ integrations; 2026 "Talk to Fireflies" in-meeting Q&A (Perplexity) | In-meeting feature answers *your* questions; doesn't suggest what to ask |
| Circleback / Fathom / Read.ai | Notes, action items, routing | Same: after-the-fact, generic |

## Category 2 — Real-time meeting coaching (closest concept)
| Product | What it does | Gap vs ReqPilot |
|---|---|---|
| **Hedy AI** | Live suggestions/coaching during meetings (Zoom/Meet/Teams/in-person) | Closest single competitor in *concept*. Generic meeting coach — no requirements methodology, no live canvas/diagrams, no BRD, no stories/Jira |
| Sales copilots (Gong, Attention, etc.) | Live battlecards/prompts for sales calls | Proves the live-prompt UX works — but sales vertical, not BA |

## Category 3 — AI requirements tools (right domain, wrong moment)
| Product | What it does | Gap vs ReqPilot |
|---|---|---|
| Copilot4DevOps | Requirement quality analysis inside Azure DevOps | Works on written requirements after the fact; no live meeting |
| Aqua | Voice-dictate a requirement → structured spec | Single-requirement dictation, not a live workshop |
| ReqSpell, Requirement, IBM DOORS+AI | Requirements management with AI assists | Document-time tools; no live capture |
| **BA Copilot (ba-copilot.com)** | Transcript/whiteboard/text → BPMN process maps | Validates diagram-from-transcript demand; not real-time, no elicitation loop; also squats the generic name |
| Miro AI / Lucidchart / Creately / Eraser | Prompt→diagram; Creately auto-captures from meetings | Canvas tools with AI bolted on; analyst still drives everything |

## Category 4 — Open-source repos (build-upon candidates)
| Repo | Health (2026-07) | Fit |
|---|---|---|
| **Meetily** (Zackriya-Solutions/meetily) | **24.4k★, MIT, active** (v0.4.0 Jun 2026, 556 commits). Rust/Tauri + Next.js. Dual-channel mic+system-audio capture, local Whisper/Parakeet real-time STT, GPU accel (Metal/CUDA/Vulkan), Ollama/Claude/Groq summaries. Win+mac installers. | **Best foundation.** Solves the hardest plumbing (Windows loopback capture + real-time local STT) under a permissive license. No live canvas/copilot/stories — that's the ReqPilot layer. Note: vendor now sells a PRO tier, so the OSS core is strategically maintained. |
| Amurex (thepersonalaicompany/amurex) | 2.8k★, **AGPL-3.0**, last release **Mar 2025 → stale ~16 months**. Chrome extension (Meet/Teams) + self-hosted backend. | Concept twin (real-time in-meeting suggestions!) — study its UX, don't build on it. Stale, AGPL (viral for a commercial product), and extension-only capture misses in-room meetings. |
| Hyprnote / Anarlog (fastrepl) | YC S25; split into Hyprnote (product) + Anarlog (MIT OSS). Local-first, mic+system audio, on-device models. Windows support was still "scheduled" as of early 2026. | Good architecture reference; second choice. Meetily is stronger on Windows today, which is Prabuddh's platform. |

## Recommendation
**Leverage Meetily, build the ReqPilot layer on top.** MIT license is safe for commercial
use; it eliminates ~4–6 weeks of audio/STT plumbing; its Next.js frontend and pluggable
LLM providers (incl. Groq — key already in hand) map directly onto ReqPilot's needs.
Everything that differentiates ReqPilot — live canvas, visual generation, elicitation
copilot, BRD builder, story/Jira pipeline — is net-new code regardless of foundation,
so starting from scratch buys nothing except the plumbing burden.

## Why this has a moat where TranslatorFlow didn't
- OS vendors and horizontal note-takers won't build BA-methodology depth (BABOK-style elicitation, requirement quality heuristics, BRD/story artifacts) — too vertical.
- The buyer (BA/consultancy) pays for *outcome* (workshop → backlog in a day), not a commodity feature.
- Workflow lock-in: session archives, traceability links, Jira/Confluence integration compound over time.
- Same reusable asset (live-audio→LLM pipeline) as TranslatorFlow, pointed at a defensible vertical — consistent with the 2026-07-14 pivot recommendation.

## Sources
- [Meetily GitHub](https://github.com/Zackriya-Solutions/meetily) · [meetily.ai](https://meetily.ai/)
- [Amurex GitHub](https://github.com/thepersonalaicompany/amurex) · [Show HN](https://news.ycombinator.com/item?id=42779378)
- [Hyprnote Launch HN (YC S25)](https://news.ycombinator.com/item?id=44725306) · [Anarlog](https://anarlog.so/)
- [Hedy AI — real-time meeting coaching](https://www.hedy.ai/post/top-5-ai-meeting-assistants/)
- [SoftSpell — AI tools for requirements gathering 2026](https://www.softspell.ai/blog/ai-tools-for-requirements-gathering)
- [Copilot4DevOps](https://copilot4devops.com/ai-in-requirements-gathering-and-documentation/)
- [BA Copilot](https://ba-copilot.com/) · [Circleback — best AI meeting assistants 2026](https://circleback.ai/blog/best-ai-meeting-assistants)
- Name scan (2026-07-14): no "ReqPilot" product found; nearest names [ReqIt.AI](https://www.aiville.com/c/ai-directory/reqit-ai) and [Copilot4DevOps "Elicit"](https://copilot4devops.com/elicit/)
