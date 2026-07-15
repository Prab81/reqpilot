"""Static browser-workflow contracts for the complete ReqPilot workspace.

These checks intentionally stay network-free. Backend behavior is covered by the API
tests; this module proves the shipped browser assets expose every supported workflow
and keep their data-shape adapters executable in a plain JavaScript runtime.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


WEB = Path(__file__).parents[1] / "src" / "web"


class _WorkflowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.inputs: list[dict[str, str | None]] = []
        self.views: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag in {"input", "textarea", "select"}:
            self.inputs.append(values)
        if values.get("data-view"):
            self.views.add(values["data-view"] or "")


def _node_eval(source: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; JavaScript adapter test skipped")
    result = subprocess.run(
        [node, "--input-type=module", "--eval", source],
        cwd=WEB,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_entry_and_workspace_surfaces_are_complete() -> None:
    parser = _WorkflowParser()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))

    assert parser.views == {"live", "brd", "stories", "jira"}
    assert {
        "entryView", "chooseLive", "chooseImport", "importDialog", "importForm",
        "transcriptFile", "importText", "importProgress", "sessionShell",
        "brdPreview", "exportBrd", "exportBrdDocx", "storiesList",
        "generateStories", "mergeStories", "jiraReadiness", "previewJira",
        "jiraPreview", "confirmJira", "exportJira", "settingsDialog", "configStatus",
    }.issubset(parser.ids)

    upload = next(item for item in parser.inputs if item.get("id") == "transcriptFile")
    assert all(extension in (upload.get("accept") or "") for extension in (".txt", ".vtt", ".docx"))


def test_application_calls_each_extended_api_contract() -> None:
    source = (WEB / "app.js").read_text(encoding="utf-8")

    required_fragments = (
        "/api/session/import",
        "/transcript`",
        "/brd.docx`",
        "/stories`",
        "/stories/generate`",
        "/stories/override`",
        "/api/config/status",
        "/jira/preview`",
        "/jira/export`",
        "new FormData()",
        "Promise.allSettled",
    )
    for fragment in required_fragments:
        assert fragment in source

    assert re.search(r"unavailable\(error\).*404\|405\|501", source, flags=re.S)
    assert "app.unavailable.add('import')" in source
    assert "app.unavailable.add('stories')" in source
    assert "app.unavailable.add('jira')" in source


def test_jira_interface_does_not_collect_or_render_stored_secrets() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    parser = _WorkflowParser()
    parser.feed(html)

    assert not any(item.get("type") == "password" for item in parser.inputs)
    assert not any((item.get("name") or "").lower() in {"token", "api_key", "secret", "password"} for item in parser.inputs)
    assert "Stored Jira credentials are never displayed" in html
    assert "Secrets are read by the server and are never returned" in html


def test_saved_session_restore_loads_all_artifact_workspaces() -> None:
    source = (WEB / "app.js").read_text(encoding="utf-8")
    reopen = re.search(r"async function reopenSession\(.*?\n  }\n\n  function resetTranscript", source, flags=re.S)
    assert reopen, "reopenSession implementation is required"
    block = reopen.group(0)
    assert "loadTranscript()" in block
    assert "loadStories()" in block
    assert "loadBrd(false)" in block
    assert "showSessionShell('saved')" in block


def test_normalizers_accept_backend_response_variants() -> None:
    module_url = (WEB / "app.js").resolve().as_uri()
    result = _node_eval(
        f"""
        import {{ normalizeTranscript, normalizeStories }} from {json.dumps(module_url)};
        const transcript = normalizeTranscript({{transcript:[
          {{id:7, content:'Need audit history', speaker_label:'Ari', start_time:12.5}},
          {{text:''}}
        ]}});
        const nested = normalizeStories({{epics:[{{key:'EP-1', summary:'Audit', stories:[{{
          key:'US-1', summary:'View history', user_story:'As an auditor...', acceptance_criteria:['Given an event']
        }}]}}]}});
        const flat = normalizeStories({{stories:[{{id:'S2', title:'Export log'}}]}});
        const packageShape = normalizeStories({{package:{{
          epics:[{{id:'E4', title:'Payments'}}],
          stories:[{{id:'US8', epic_id:'E4', title:'Refund', as_a:'clerk', i_want:'to refund', so_that:'errors are corrected',
            acceptance_criteria:[{{given:'a settled payment', when:'I refund it', then:'a credit is recorded'}}]}}]
        }}}});
        console.log(JSON.stringify({{
          transcript: transcript[0], nestedEpic: nested[0].id,
          nestedStory: nested[0].stories[0], flatEpic: flat[0].id, flatCount: flat[0].stories.length,
          packageStory: packageShape[0].stories[0]
        }}));
        """
    )
    assert result["transcript"] == {
        "utterance_id": 7, "text": "Need audit history", "speaker": "Ari", "t0": 12.5, "t1": 0
    }
    assert result["nestedEpic"] == "EP-1"
    assert result["nestedStory"]["id"] == "US-1"
    assert result["nestedStory"]["text"] == "As an auditor..."
    assert result["nestedStory"]["acceptance_criteria"] == ["Given an event"]
    assert result["flatEpic"] == "E1"
    assert result["flatCount"] == 1
    assert result["packageStory"]["id"] == "US8"
    assert result["packageStory"]["text"].startswith("As a clerk")
    assert result["packageStory"]["acceptance_criteria"] == [
        "Given a settled payment, when I refund it, then a credit is recorded."
    ]


def test_new_views_remain_responsive_and_keyboard_visible() -> None:
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert ".mode-grid" in css
    assert ".document-layout" in css
    assert ".jira-grid" in css
    assert "@media (max-width: 880px)" in css
    assert "@media (max-width: 520px)" in css
    assert ":focus-visible" in css
    assert "[hidden] { display: none !important; }" in css
