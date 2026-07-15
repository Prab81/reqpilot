"""Focused, network-free checks for the Phase-Live browser assets."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


WEB = Path(__file__).parents[1] / "src" / "web"


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.scripts: list[str] = []
        self.landmarks: list[str] = []
        self.dialogs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"] or "")
        if tag in {"main", "aside", "nav", "header"}:
            self.landmarks.append(tag)
        if tag == "dialog" and values.get("id"):
            self.dialogs.append(values["id"] or "")


def _node_eval(source: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; browser pure-function check skipped")
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", source],
        cwd=WEB,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_document_has_complete_unique_three_pane_contract() -> None:
    parser = _DocumentParser()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))

    assert len(parser.ids) == len(set(parser.ids)), "HTML ids must remain unique"
    assert {"main", "aside", "nav", "header"}.issubset(parser.landmarks)
    assert {"sessionsDialog", "editDialog"}.issubset(parser.dialogs)
    required = {
        "startSession", "pauseSession", "stopSession", "micDevice",
        "transcript", "summaryList", "requirementsList", "decisionsList",
        "visualsList", "questionList", "gapsList", "exportBrd",
    }
    assert required.issubset(parser.ids)
    assert parser.scripts == ["./vendor/mermaid.min.js", "./app.js"]


def test_assets_are_local_and_include_accessible_responsive_states() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")

    assert not re.search(r"(?:src|href)=[\"']https?://", html, flags=re.I)
    assert 'role="alert"' in html
    assert 'aria-live="polite"' in html
    assert 'role="progressbar"' in html
    assert "@media (max-width: 880px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ":focus-visible" in css


def test_application_exposes_protocol_and_feature_hooks() -> None:
    source = (WEB / "app.js").read_text(encoding="utf-8")

    for control_type in ("start", "stop"):
        assert f"type: '{control_type}'" in source
    for event_type in ("partial", "final", "state", "status", "error"):
        assert f"case '{event_type}'" in source
    for action in ("pin", "dismiss", "edit", "asked", "answered", "parked"):
        assert action in source
    assert "window.mermaid.render" in source
    assert "diagramFallback" in source
    assert "new Blob([markdown]" in source
    assert "WebSocket" in source


def test_pure_application_helpers_normalize_and_format_safely() -> None:
    module_url = (WEB / "app.js").resolve().as_uri()
    result = _node_eval(
        f"""
        import {{ normalizeState, safeFilename, formatTime, calculateCoverage }} from {json.dumps(module_url)};
        const state = normalizeState({{
          title: 'Checkout', summary: ['One'], requirements: [{{id:'R1', status:'confirmed'}}],
          open_questions: [{{id:'Q1', status:'answered'}}], diagrams: 'invalid'
        }});
        console.log(JSON.stringify({{
          title: state.title, diagrams: state.diagrams.length,
          filename: safeFilename('Discovery: ACME / Q3?'), time: formatTime(3661),
          coverage: calculateCoverage(state), missing: normalizeState(null).requirements.length
        }}));
        """
    )
    assert result == {
        "title": "Checkout",
        "diagrams": 0,
        "filename": "Discovery-ACME-Q3",
        "time": "1:01:01",
        "coverage": 100,
        "missing": 0,
    }


def test_downsampler_produces_16khz_non_silent_frequency_preserving_pcm() -> None:
    module_url = (WEB / "worklet.js").resolve().as_uri()
    result = _node_eval(
        f"""
        import {{ resampleLinear }} from {json.dumps(module_url)};
        const input = Float32Array.from({{length: 48000}}, (_, i) => Math.sin(2 * Math.PI * 1000 * i / 48000));
        const output = resampleLinear(input, 48000, 16000);
        let crossings = 0, energy = 0;
        for (let i = 1; i < output.length; i++) {{
          if (output[i - 1] <= 0 && output[i] > 0) crossings++;
          energy += output[i] * output[i];
        }}
        console.log(JSON.stringify({{length: output.length, crossings, rms: Math.sqrt(energy / output.length)}}));
        """
    )
    assert result["length"] == 16_000
    assert abs(result["crossings"] - 1_000) <= 1
    assert math.isclose(result["rms"], 2**-0.5, rel_tol=0.01)


def test_microphone_errors_keep_denied_capture_actionable() -> None:
    module_url = (WEB / "audio-capture.js").resolve().as_uri()
    result = _node_eval(
        f"""
        import {{ micConstraints, micErrorMessage }} from {json.dumps(module_url)};
        console.log(JSON.stringify({{
          denied: micErrorMessage({{name:'NotAllowedError'}}),
          exact: micConstraints('mic-2').audio.deviceId.exact,
          echo: micConstraints().audio.echoCancellation
        }}));
        """
    )
    assert "denied" in result["denied"].lower()
    assert "read-only" in result["denied"]
    assert result["exact"] == "mic-2"
    assert result["echo"] is False
