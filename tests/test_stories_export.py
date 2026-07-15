"""Backlog file exports: styled DOCX structure, RFC 4180 CSV, and API routes."""
from __future__ import annotations

import copy
import csv
import io
from typing import Any

from fastapi.testclient import TestClient

from src.delivery import StoryService, build_stories_docx, stories_csv
from src.intelligence.providers import MockProvider
from src.server import create_app
from src.sessions.store import SessionStore
from tests.fixtures.meeting_transcript import pass2_state, utterances


DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

_STORY_RESPONSE: dict[str, Any] = {
    "title": "Consumer lending delivery backlog",
    "epics": [
        {"id": "E1", "title": "Digital application intake",
         "description": "Capture applications once and route them consistently.",
         "requirement_ids": ["R1", "R7"], "evidence_utterances": [5, 14]},
        {"id": "E2", "title": "Underwriting workflow",
         "description": "Give underwriting a controlled and observable workflow.",
         "requirement_ids": ["R3", "R4"], "evidence_utterances": [8, 10]},
    ],
    "stories": [
        {"id": "US1", "epic_id": "E1", "title": "Ingest website applications",
         "as_a": "loan operations analyst",
         "i_want": "website applications captured automatically",
         "so_that": "applicant details are not re-keyed",
         "acceptance_criteria": [
             {"given": "a complete website application", "when": "it is submitted",
              "then": "its applicant data is recorded once in the intake system"},
             {"given": "a recorded website application", "when": "operations opens it",
              "then": "the source is identified as website"},
         ],
         "requirement_ids": ["R1"], "evidence_utterances": [2, 5]},
        {"id": "US2", "epic_id": "E2", "title": "Route incomplete applications",
         "as_a": "senior underwriter",
         "i_want": "incomplete applications in a manual queue",
         "so_that": "missing documents can be resolved",
         "acceptance_criteria": [
             {"given": "an application missing a required document",
              "when": "validation completes",
              "then": "the application is placed in the manual review queue"},
         ],
         "requirement_ids": ["R3"], "evidence_utterances": [8, 21]},
    ],
}


def _seeded_store(tmp_path) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path / "data")
    session_id = store.create_session("Loan workshop")
    for utterance in utterances():
        store.append_utterance(session_id, utterance)
    store.snapshot_state(session_id, pass2_state(), 2, analyzed_through=30)
    return store, session_id


def _package_and_session(tmp_path) -> tuple[dict[str, Any], dict[str, Any]]:
    store, session_id = _seeded_store(tmp_path)
    service = StoryService(store, MockProvider([copy.deepcopy(_STORY_RESPONSE)]))
    package = service.generate(session_id)["package"]
    return package, store.load_session(session_id)


def test_backlog_docx_has_epic_headings_story_sections_and_ac_tables(tmp_path) -> None:
    package, session = _package_and_session(tmp_path)
    doc = build_stories_docx(package, session)

    heading1 = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert any("E1" in text and "Digital application intake" in text for text in heading1)
    assert any("E2" in text and "Underwriting workflow" in text for text in heading1)
    heading2 = [p.text for p in doc.paragraphs if p.style.name == "Heading 2"]
    assert any("US1" in text and "Ingest website applications" in text for text in heading2)
    assert any("US2" in text for text in heading2)

    ac_tables = [table for table in doc.tables
                 if [cell.text for cell in table.rows[0].cells] == ["ID", "Given", "When", "Then"]]
    assert len(ac_tables) == 2
    assert len(ac_tables[0].rows) == 3  # header + two criteria for US1
    assert len(ac_tables[1].rows) == 2  # header + one criterion for US2
    assert ac_tables[0].rows[1].cells[0].text == "US1-AC1"
    assert ac_tables[0].rows[1].cells[1].text == "a complete website application"


def test_backlog_docx_traceability_uses_requirements_and_mmss_timestamps(tmp_path) -> None:
    package, session = _package_and_session(tmp_path)
    doc = build_stories_docx(package, session)

    text = "\n".join(p.text for p in doc.paragraphs)
    assert "As a loan operations analyst, I want website applications captured automatically, " \
           "so that applicant details are not re-keyed." in text
    # Epic E1 evidence: U5 (t0=33.2s) and U14 (t0=108.5s); story US1 references R1.
    assert "Traceability: requirements R1, R7 · evidence 00:33 (U5), 01:48 (U14)" in text
    assert "Traceability: requirements R1 · evidence 00:08 (U2), 00:33 (U5)" in text
    assert f"Session: {session['id']}" == next(
        p.text for p in doc.paragraphs if p.text.startswith("Session: "))


def test_backlog_csv_header_rows_and_crlf_are_exact(tmp_path) -> None:
    package, _session = _package_and_session(tmp_path)
    text = stories_csv(package)

    assert text.startswith(
        "Issue Type,Key,Summary,Description,Acceptance Criteria,Epic,Requirements,Evidence\r\n"
    )
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 1 + len(package["epics"]) + len(package["stories"])
    assert text.count("\r\n") == len(rows)  # RFC 4180 CRLF terminator on every row

    epic_row = rows[1]
    assert epic_row[:3] == ["Epic", "E1", "Digital application intake"]
    assert epic_row[5] == ""  # epics do not reference a parent epic
    assert epic_row[6] == "R1, R7"
    assert epic_row[7] == "U5, U14"

    story_row = rows[3]
    assert story_row[0] == "Story"
    assert story_row[1] == "US1"
    assert story_row[3] == ("As a loan operations analyst, I want website applications "
                            "captured automatically, so that applicant details are not re-keyed.")
    assert story_row[4] == (
        "Given a complete website application When it is submitted "
        "Then its applicant data is recorded once in the intake system | "
        "Given a recorded website application When operations opens it "
        "Then the source is identified as website"
    )
    assert story_row[5] == "E1: Digital application intake"


def test_backlog_csv_quotes_commas_quotes_and_newlines(tmp_path) -> None:
    package, _session = _package_and_session(tmp_path)
    package["epics"][0]["description"] = 'Handles "quotes", commas,\nand newlines'

    text = stories_csv(package)

    assert '"Handles ""quotes"", commas,\nand newlines"' in text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1][3] == 'Handles "quotes", commas,\nand newlines'
    assert len(rows) == 1 + len(package["epics"]) + len(package["stories"])


def test_export_routes_return_404_before_generation_and_files_after(tmp_path) -> None:
    store, session_id = _seeded_store(tmp_path)
    client = TestClient(create_app(
        store=store, provider=MockProvider([copy.deepcopy(_STORY_RESPONSE)])
    ))

    for suffix in ("stories.docx", "stories.csv"):
        missing = client.get(f"/api/session/{session_id}/{suffix}")
        assert missing.status_code == 404
        assert "no delivery package" in str(missing.json()["detail"])

    assert client.post(f"/api/session/{session_id}/stories/generate").status_code == 200

    document = client.get(f"/api/session/{session_id}/stories.docx")
    assert document.status_code == 200
    assert document.headers["content-type"] == DOCX_MEDIA_TYPE
    assert f"reqpilot-backlog-{session_id}.docx" in document.headers["content-disposition"]
    assert document.content.startswith(b"PK")

    sheet = client.get(f"/api/session/{session_id}/stories.csv")
    assert sheet.status_code == 200
    assert sheet.headers["content-type"] == "text/csv; charset=utf-8"
    assert f"reqpilot-backlog-{session_id}.csv" in sheet.headers["content-disposition"]
    assert sheet.text.startswith("Issue Type,Key,Summary,")


def test_export_routes_reject_unknown_sessions(tmp_path) -> None:
    client = TestClient(create_app(
        store=SessionStore(tmp_path / "data"), provider=MockProvider([])
    ))
    assert client.get("/api/session/missing/stories.docx").status_code == 404
    assert client.get("/api/session/missing/stories.csv").status_code == 404
