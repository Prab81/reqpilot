from __future__ import annotations

from zipfile import ZipFile

from docx import Document
from lxml import etree

from src.delivery import export_brd_docx
from src.intelligence.providers import MockProvider
from src.sessions.store import SessionStore
from tests.fixtures.meeting_transcript import brd_narrative, pass2_state, utterances


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _session(tmp_path) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path / "data")
    sid = store.create_session()
    for utterance in utterances():
        store.append_utterance(sid, utterance)
    store.snapshot_state(sid, pass2_state(), 2, analyzed_through=30)
    return store, sid


def test_docx_export_contains_all_requirements_and_timestamp_evidence(tmp_path) -> None:
    store, sid = _session(tmp_path)
    path = export_brd_docx(sid, store, MockProvider([brd_narrative()]), tmp_path / "BRD.docx")

    document = Document(path)
    text = "\n".join(p.text for p in document.paragraphs)
    table_text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert "Business Requirements Document" in text or "BRD" in text
    assert "Transcript Evidence Register" in text
    for requirement in pass2_state()["requirements"]:
        assert requirement["id"] in table_text
        assert requirement["text"] in table_text
    assert "00:08 (U2)" in table_text
    assert "U30" in table_text and "04:01-04:08" in table_text


def test_docx_uses_real_styles_numbering_and_fixed_dxa_geometry(tmp_path) -> None:
    store, sid = _session(tmp_path)
    path = export_brd_docx(sid, store, MockProvider([brd_narrative()]), tmp_path / "BRD.docx")

    with ZipFile(path) as archive:
        document_xml = etree.fromstring(archive.read("word/document.xml"))
        styles_xml = etree.fromstring(archive.read("word/styles.xml"))
        numbering_xml = etree.fromstring(archive.read("word/numbering.xml"))
    assert document_xml.xpath("count(.//w:pStyle[@w:val='Heading1'])", namespaces=NS) >= 1
    assert document_xml.xpath("count(.//w:numPr/w:numId)", namespaces=NS) >= 1
    assert numbering_xml.xpath("count(.//w:abstractNum/w:lvl/w:numFmt[@w:val='bullet'])", namespaces=NS) >= 1
    assert styles_xml.xpath("string(.//w:style[@w:styleId='Normal']/w:pPr/w:spacing/@w:after)", namespaces=NS) == "120"
    for table in document_xml.xpath(".//w:tbl", namespaces=NS):
        assert table.xpath("string(w:tblPr/w:tblW/@w:type)", namespaces=NS) == "dxa"
        assert table.xpath("string(w:tblPr/w:tblW/@w:w)", namespaces=NS) == "9360"
        assert table.xpath("string(w:tblPr/w:tblInd/@w:w)", namespaces=NS) == "120"
        assert table.xpath(
            "count(w:tr[1]/w:trPr/w:tblHeader)", namespaces=NS
        ) == 1
        grid = [int(value) for value in table.xpath("w:tblGrid/w:gridCol/@w:w", namespaces=NS)]
        assert sum(grid) == 9360
        for row in table.xpath("w:tr", namespaces=NS):
            widths = [int(value) for value in row.xpath("w:tc/w:tcPr/w:tcW/@w:w", namespaces=NS)]
            assert widths == grid


def test_docx_degrades_to_deterministic_content_when_provider_fails(tmp_path) -> None:
    store, sid = _session(tmp_path)
    path = export_brd_docx(sid, store, MockProvider([]), tmp_path / "fallback.docx")

    document = Document(path)
    table_text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    assert path.stat().st_size > 10_000
    assert "R14" in table_text
    assert "03:53 (U29)" in table_text
