from __future__ import annotations

from pathlib import Path

from scripts import diagnose


def test_model_check_requires_a_nonempty_directory(tmp_path: Path) -> None:
    assert diagnose._model_check("offline", tmp_path)["ok"] is False
    (tmp_path / "model.onnx").write_bytes(b"model")
    assert diagnose._model_check("offline", tmp_path)["ok"] is True


def test_diagnostics_treats_jira_as_optional(monkeypatch) -> None:
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)

    result = diagnose.collect_diagnostics()

    jira = next(check for check in result["checks"] if check["name"] == "jira_configuration")
    assert jira == {
        "name": "jira_configuration", "ok": False,
        "optional": True, "configured": False,
    }
