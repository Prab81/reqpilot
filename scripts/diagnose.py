"""Run non-destructive ReqPilot readiness checks.

This command never sends meeting content or calls a cloud LLM. It checks local
paths and configuration, and optionally probes a running ReqPilot server.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from src import config


def _model_check(kind: str, path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.is_dir() else []
    return {
        "name": f"asr_{kind}",
        "ok": path.is_dir() and bool(files),
        "path": str(path),
        "files": len(files),
    }


def collect_diagnostics(server_url: str | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 11),
            "version": ".".join(map(str, sys.version_info[:3])),
        },
        _model_check("offline", Path(config.OFFLINE_MODEL_DIR)),
        _model_check("streaming", Path(config.STREAMING_MODEL_DIR)),
        {
            "name": "data_directory",
            "ok": config.DATA_DIR.parent.exists(),
            "path": str(config.DATA_DIR),
        },
    ]

    provider = config.PROVIDER.strip().lower()
    provider_ok = {
        "ollama": bool(config.OLLAMA_BASE_URL and config.OLLAMA_MODEL),
        "groq": bool(config.GROQ_API_KEY),
        "anthropic": bool(config.ANTHROPIC_API_KEY),
    }.get(provider, False)
    checks.append({
        "name": "provider_configuration",
        "ok": provider_ok,
        "provider": provider,
        "model": {
            "ollama": config.OLLAMA_MODEL,
            "groq": config.GROQ_MODEL,
            "anthropic": config.ANTHROPIC_MODEL,
        }.get(provider, ""),
    })

    jira_values = [
        os.environ.get("JIRA_BASE_URL", ""),
        os.environ.get("JIRA_EMAIL", ""),
        os.environ.get("JIRA_API_TOKEN", ""),
        os.environ.get("JIRA_PROJECT_KEY", ""),
    ]
    checks.append({
        "name": "jira_configuration",
        "ok": all(jira_values),
        "optional": True,
        "configured": all(jira_values),
    })

    if server_url:
        try:
            response = httpx.get(
                f"{server_url.rstrip('/')}/api/config/status", timeout=5.0
            )
            response.raise_for_status()
            checks.append({
                "name": "server",
                "ok": True,
                "url": server_url,
                "status": response.json(),
            })
        except (httpx.HTTPError, ValueError) as exc:
            checks.append({
                "name": "server", "ok": False, "url": server_url,
                "error": str(exc),
            })

    required = [check for check in checks if not check.get("optional")]
    return {"ready": all(check["ok"] for check in required), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server",
        nargs="?",
        const="http://127.0.0.1:8765",
        help="also probe a running server (default: http://127.0.0.1:8765)",
    )
    args = parser.parse_args()
    result = collect_diagnostics(args.server)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()
