"""Fixture: a scripted ~30-utterance requirements meeting about a consumer
loan-approval workflow, plus canned LLM state responses for MockProvider.

The script deliberately contains:
- explicit volumes (U4: ~1,200/month, 70% website; U13: month-end doubles)
- an exception path (U8: missing documents -> manual review queue + email)
- one contradiction (U7 auto-approval vs U24 mandatory credit-officer
  sign-off, acknowledged in U25)

PASS_1_STATE models the engine output after U1-U8; PASS_2_STATE after U9-U30
(IDs from pass 1 preserved). BRD_NARRATIVE is a canned narrative-sections
response for the BRD prompt.
"""
from __future__ import annotations

import copy
from typing import Any

from src.intelligence.state import Utterance

_SCRIPT: list[tuple[int, float, float, str]] = [
    (1, 0.0, 7.8, "Thanks everyone for joining. Today I want to walk through how we handle consumer loan applications, because the current process is slow and error-prone."),
    (2, 8.4, 15.9, "Right now an application comes in either through a branch or through the website, and it lands in a shared inbox as a PDF attachment."),
    (3, 16.5, 24.2, "Someone on the operations team picks it up, re-keys all the applicant details into the core banking system by hand, and then orders a credit report."),
    (4, 24.8, 32.6, "For volume context, we receive about twelve hundred loan applications a month, and roughly seventy percent of those come in through the website."),
    (5, 33.2, 40.7, "The first thing the new system must do is pull website applications straight from the online form, so nobody is re-typing PDFs."),
    (6, 41.3, 49.5, "Once the credit report comes back, an underwriter reviews the full file and either approves it, declines it, or asks the applicant for more documents."),
    (7, 50.1, 58.9, "For loans under fifty thousand dollars, if the credit score is above seven hundred, the system should auto-approve without any human touch."),
    (8, 59.5, 67.8, "If any required document is missing, the application should be routed to a manual review queue and the applicant should automatically get an email listing what's missing."),
    (9, 68.4, 75.2, "One thing we've already decided: we are keeping the core banking system. This is an integration project, not a replacement."),
    (10, 75.8, 83.1, "The underwriters also want a single work queue, ordered by application age, instead of digging through the shared inbox."),
    (11, 83.7, 91.4, "Applicants should get an SMS and an email at every status change — received, in review, approved, declined."),
    (12, 92.0, 99.6, "Our service standard is a decision within twenty-four hours for standard applications. The new system has to help us hit that."),
    (13, 100.2, 107.9, "At month-end the volume roughly doubles, so whatever we build has to keep up with those spikes."),
    (14, 108.5, 116.3, "Branch staff will still key in paper applications, but they should use the same intake form as the website so everything lands in one place."),
    (15, 116.9, 124.4, "When an application is declined, we need to send the adverse action notice — that's a regulatory requirement, it can't be missed."),
    (16, 125.0, 132.8, "Management also wants a weekly dashboard showing application volumes and approval rates, split by channel."),
    (17, 133.4, 140.6, "Good question about the credit report — we use Experian today, and there are no plans to change bureau."),
    (18, 141.2, 149.0, "If the credit bureau is down or times out, the application shouldn't get stuck — park it in a retry state and alert the ops team."),
    (19, 149.6, 157.2, "For audit, every status change needs a timestamped record of who or what triggered it. The regulators check this."),
    (20, 157.8, 165.5, "The manual review queue is handled by the senior underwriting team — there are four of them today."),
    (21, 166.1, 173.8, "On documents: for a standard consumer loan we require proof of income, a government ID, and three months of bank statements."),
    (22, 174.4, 182.0, "Self-employed applicants are the tricky case — they need two years of tax returns instead of pay slips, and those files get big."),
    (23, 182.6, 190.3, "We should probably talk about limits — the maximum consumer loan we write is two hundred and fifty thousand dollars."),
    (24, 190.9, 199.7, "Actually, hold on — compliance told us last week that every single approval now needs a credit officer sign-off. No exceptions, not even the small loans."),
    (25, 200.3, 208.1, "Hmm, that does conflict with the auto-approval idea. Let's flag it and I'll take it to compliance — maybe sign-off can be a batch review after the fact."),
    (26, 208.7, 216.4, "Okay. On the applicant experience, they should be able to check their application status online without calling the branch."),
    (27, 217.0, 224.6, "Data retention: closed applications have to be kept for seven years, then purged. Legal is firm on that."),
    (28, 225.2, 232.9, "For rollout we'd want the website intake and the underwriter queue first — the dashboard and SMS notifications can come later."),
    (29, 233.5, 241.2, "One more thing — the system should flag any application where the stated income looks inconsistent with the bank statements, for fraud review."),
    (30, 241.8, 248.9, "Great. Let's get these written up. I think the priority is killing the re-keying and hitting the twenty-four-hour decision standard."),
]


def utterances() -> list[Utterance]:
    """Fresh Utterance objects for the full scripted meeting."""
    return [Utterance(id=i, t0=t0, t1=t1, text=text) for i, t0, t1, text in _SCRIPT]


MERMAID_PASS_1 = """\
flowchart TD
  A["Application submitted via website or branch"] --> B["Details entered in core banking system"]
  B --> C["Credit report ordered"]
  C --> D{"All required documents present?"}
  D -->|"No"| E["Route to manual review queue"]
  E --> F["Email applicant the missing documents"]
  D -->|"Yes"| G{"Under $50,000 and score above 700?"}
  G -->|"Yes"| H["Auto-approve"]
  G -->|"No"| I["Underwriter review"]
  I --> J["Approve, decline, or request more documents"]"""

MERMAID_PASS_2 = """\
flowchart TD
  A["Application submitted via website or branch intake form"] --> B["Details recorded in core banking system"]
  B --> C["Credit report ordered from Experian"]
  C --> D{"All required documents present?"}
  D -->|"No"| E["Route to manual review queue"]
  E --> F["Email applicant the missing documents"]
  D -->|"Yes"| G{"Under $50,000 and score above 700?"}
  G -->|"Yes"| H["Auto-approve (pending compliance ruling)"]
  G -->|"No"| I["Underwriter review"]
  I --> J{"Underwriter decision"}
  J -->|"Approve"| K["Credit officer sign-off"]
  H --> K
  J -->|"Decline"| L["Send adverse action notice"]
  J -->|"More documents"| E"""


_PASS_1_STATE: dict[str, Any] = {
    "title": "Consumer Loan Application Processing",
    "summary": [
        "Current intake is manual: applications arrive as PDFs in a shared inbox and are re-keyed into the core banking system.",
        "Volume is about 1,200 applications/month, roughly 70% via the website.",
        "Website applications must flow directly from the online form — no re-keying.",
        "Loans under $50k with credit score above 700 should auto-approve; missing documents route to a manual review queue with an automatic applicant email.",
    ],
    "requirements": [
        {"id": "R1", "text": "Website applications are ingested directly from the online form into the system, eliminating manual re-keying of PDFs.",
         "status": "captured", "evidence_utterances": [2, 3, 5]},
        {"id": "R2", "text": "Loans under $50,000 with a credit score above 700 are auto-approved with no human touch.",
         "status": "captured", "evidence_utterances": [7]},
        {"id": "R3", "text": "Applications missing any required document are routed to a manual review queue and the applicant automatically receives an email listing the missing items.",
         "status": "captured", "evidence_utterances": [8]},
    ],
    "decisions": [],
    "open_questions": [
        {"id": "Q1", "text": "What share of the ~1,200 monthly applications fall under the $50,000 auto-approval threshold?",
         "status": "suggested", "requirement_id": "R2", "category": "volumes"},
        {"id": "Q2", "text": "If the credit score is exactly 700, or the bureau returns no score, what happens to an under-$50k application?",
         "status": "suggested", "requirement_id": "R2", "category": "exceptions"},
        {"id": "Q3", "text": "Who works the manual review queue, and what turnaround is expected for it?",
         "status": "suggested", "requirement_id": "R3", "category": "actors"},
        {"id": "Q4", "text": "Which documents count as 'required documents' for a standard application?",
         "status": "suggested", "requirement_id": "R3", "category": "data"},
        {"id": "Q5", "text": "Which fields does the online form capture today, and do they map one-to-one onto the core banking system?",
         "status": "suggested", "requirement_id": "R1", "category": "data"},
    ],
    "diagrams": [
        {"id": "G1", "kind": "flowchart", "title": "Loan application processing flow",
         "mermaid": MERMAID_PASS_1, "evidence_utterances": [2, 3, 6, 7, 8]},
    ],
    "metrics": [
        {"id": "M1", "title": "Application volume by channel (monthly)", "kind": "pie",
         "labels": ["Website", "Branch"], "values": [840, 360],
         "evidence_utterances": [4]},
    ],
    "gaps": [
        {"id": "X1", "text": "'Required documents' (U8) are referenced but never defined.",
         "category": "definitions", "evidence_utterances": [8]},
    ],
}


_PASS_2_STATE: dict[str, Any] = {
    "title": "Consumer Loan Application Processing",
    "summary": [
        "Replace manual PDF re-keying with direct intake from a shared web/branch form; volume ~1,200/month (70% web), doubling at month-end.",
        "Underwriters get a single age-ordered work queue; senior underwriting team of four handles manual review.",
        "Decision standard: 24 hours for standard applications; adverse action notice is mandatory on decline.",
        "Conflict flagged: auto-approval under $50k vs compliance's new rule that every approval needs credit officer sign-off — owner taking it to compliance.",
        "Phase 1 delivers website intake and the underwriter queue; dashboard and SMS notifications follow.",
    ],
    "requirements": [
        {"id": "R1", "text": "Website applications are ingested directly from the online form into the system, eliminating manual re-keying of PDFs.",
         "status": "confirmed", "evidence_utterances": [2, 3, 5, 30]},
        {"id": "R2", "text": "Loans under $50,000 with a credit score above 700 are auto-approved with no human touch.",
         "status": "clarifying", "evidence_utterances": [7, 24, 25]},
        {"id": "R3", "text": "Applications missing any required document (proof of income, government ID, three months of bank statements; two years of tax returns for self-employed) are routed to a manual review queue and the applicant automatically receives an email listing the missing items.",
         "status": "confirmed", "evidence_utterances": [8, 21, 22]},
        {"id": "R4", "text": "Underwriters work from a single queue ordered by application age.",
         "status": "captured", "evidence_utterances": [10]},
        {"id": "R5", "text": "Applicants receive an SMS and an email at every status change (received, in review, approved, declined).",
         "status": "captured", "evidence_utterances": [11]},
        {"id": "R6", "text": "Standard applications receive a decision within 24 hours.",
         "status": "captured", "evidence_utterances": [12, 30]},
        {"id": "R7", "text": "Branch staff enter paper applications through the same intake form as the website.",
         "status": "captured", "evidence_utterances": [14]},
        {"id": "R8", "text": "Declined applications automatically trigger the regulatory adverse action notice.",
         "status": "captured", "evidence_utterances": [15]},
        {"id": "R9", "text": "A weekly dashboard shows application volumes and approval rates split by channel.",
         "status": "captured", "evidence_utterances": [16]},
        {"id": "R10", "text": "If the credit bureau is unavailable or times out, the application is parked in a retry state and the ops team is alerted.",
         "status": "captured", "evidence_utterances": [18]},
        {"id": "R11", "text": "Every status change writes a timestamped audit record of who or what triggered it.",
         "status": "captured", "evidence_utterances": [19]},
        {"id": "R12", "text": "Applicants can check their application status online without contacting the branch.",
         "status": "captured", "evidence_utterances": [26]},
        {"id": "R13", "text": "Closed applications are retained for seven years and then purged.",
         "status": "captured", "evidence_utterances": [27]},
        {"id": "R14", "text": "Applications where stated income is inconsistent with bank statements are flagged for fraud review.",
         "status": "captured", "evidence_utterances": [29]},
    ],
    "decisions": [
        {"id": "D1", "text": "The core banking system stays; this is an integration project, not a replacement.",
         "evidence_utterances": [9]},
        {"id": "D2", "text": "Experian remains the credit bureau; no plans to change.",
         "evidence_utterances": [17]},
        {"id": "D3", "text": "Rollout phase 1 is website intake plus the underwriter queue; dashboard and SMS notifications come later.",
         "evidence_utterances": [28]},
    ],
    "open_questions": [
        {"id": "Q1", "text": "What share of the ~1,200 monthly applications fall under the $50,000 auto-approval threshold?",
         "status": "suggested", "requirement_id": "R2", "category": "volumes"},
        {"id": "Q2", "text": "If the credit score is exactly 700, or the bureau returns no score, what happens to an under-$50k application?",
         "status": "suggested", "requirement_id": "R2", "category": "exceptions"},
        {"id": "Q3", "text": "Who works the manual review queue, and what turnaround is expected for it?",
         "status": "answered", "requirement_id": "R3", "category": "actors"},
        {"id": "Q4", "text": "Which documents count as 'required documents' for a standard application?",
         "status": "answered", "requirement_id": "R3", "category": "data"},
        {"id": "Q5", "text": "Which fields does the online form capture today, and do they map one-to-one onto the core banking system?",
         "status": "suggested", "requirement_id": "R1", "category": "data"},
        {"id": "Q6", "text": "Does the 24-hour decision clock start at submission or once all required documents are complete?",
         "status": "suggested", "requirement_id": "R6", "category": "acceptance"},
        {"id": "Q7", "text": "How long may an application sit in the bureau-retry state before it must be escalated?",
         "status": "suggested", "requirement_id": "R10", "category": "exceptions"},
        {"id": "Q8", "text": "What difference between stated income and bank-statement income should trigger the fraud flag?",
         "status": "suggested", "requirement_id": "R14", "category": "data"},
        {"id": "Q9", "text": "Can the credit officer sign-off (U24) be a post-hoc batch review so under-$50k auto-approval survives?",
         "status": "asked", "requirement_id": "R2", "category": "exceptions"},
    ],
    "diagrams": [
        {"id": "G1", "kind": "flowchart", "title": "Loan application processing flow",
         "mermaid": MERMAID_PASS_2, "evidence_utterances": [2, 3, 6, 7, 8, 15, 24]},
    ],
    "metrics": [
        {"id": "M1", "title": "Application volume by channel (monthly)", "kind": "pie",
         "labels": ["Website", "Branch"], "values": [840, 360],
         "evidence_utterances": [4]},
        {"id": "M2", "title": "Monthly application volume: average vs month-end peak", "kind": "bar",
         "labels": ["Average month", "Month-end peak"], "values": [1200, 2400],
         "evidence_utterances": [4, 13]},
    ],
    "gaps": [
        {"id": "X2", "text": "Conflict: U7 says loans under $50k with score above 700 auto-approve with no human touch, but U24 says every approval requires a credit officer sign-off with no exceptions.",
         "category": "conflict", "evidence_utterances": [7, 24]},
        {"id": "X3", "text": "Month-end volume doubles (U13) but no throughput or response-time target has been stated for the intake pipeline.",
         "category": "nfr", "evidence_utterances": [13]},
        {"id": "X4", "text": "The credit officer role (U24) has not been identified — who holds it and how many officers are available?",
         "category": "actors", "evidence_utterances": [24]},
    ],
}


_BRD_NARRATIVE: dict[str, Any] = {
    "title": "BRD — Consumer Loan Application Processing",
    "context": (
        "The bank receives about 1,200 consumer loan applications per month, roughly 70% "
        "through the website, with volume roughly doubling at month-end. Applications currently "
        "arrive as PDF attachments in a shared inbox and are re-keyed by the operations team "
        "into the core banking system, a process described as slow and error-prone.\n\n"
        "This initiative replaces the manual intake with direct capture from a shared web/branch "
        "form, gives underwriters a single age-ordered work queue, and supports the bank's "
        "24-hour decision standard for standard applications."
    ),
    "stakeholders": [
        {"name": "Applicants", "interest": "Fast decisions, status visibility online, and notifications at every status change."},
        {"name": "Operations team", "interest": "Elimination of PDF re-keying; alerts when bureau retries need attention."},
        {"name": "Underwriters", "interest": "A single work queue ordered by application age."},
        {"name": "Senior underwriting team (4 people)", "interest": "Owns the manual review queue for incomplete applications."},
        {"name": "Credit officers / Compliance", "interest": "Sign-off on approvals; adverse action notices; audit trail."},
        {"name": "Management", "interest": "Weekly dashboard of volumes and approval rates by channel."},
    ],
    "current_process": (
        "Applications arrive via a branch or the website and land in a shared inbox as PDF "
        "attachments. An operations team member re-keys applicant details into the core banking "
        "system and orders an Experian credit report. When the report returns, an underwriter "
        "reviews the file and approves, declines, or requests more documents."
    ),
    "future_process": (
        "Website applications flow directly from the online form; branch staff use the same "
        "intake form for paper applications. Complete applications with a credit report proceed "
        "to underwriting via a single age-ordered queue; under-$50k applications with a score "
        "above 700 auto-approve, pending resolution of the compliance sign-off conflict. "
        "Incomplete applications route to the senior underwriting team's manual review queue "
        "with an automatic email to the applicant listing missing documents. Declines trigger "
        "the adverse action notice automatically."
    ),
    "non_functional": [
        "Decision within 24 hours for standard applications.",
        "Capacity for month-end spikes of roughly double the average volume.",
        "Timestamped audit record of who or what triggered every status change.",
        "Closed applications retained seven years, then purged.",
    ],
    "assumptions": [
        "The core banking system remains and exposes integration points for intake and status updates (U9).",
        "Experian remains the sole credit bureau (U17).",
        "The senior underwriting team of four can absorb the manual review queue volume (U20).",
    ],
}


def pass1_state() -> dict[str, Any]:
    return copy.deepcopy(_PASS_1_STATE)


def pass2_state() -> dict[str, Any]:
    return copy.deepcopy(_PASS_2_STATE)


def brd_narrative() -> dict[str, Any]:
    return copy.deepcopy(_BRD_NARRATIVE)
