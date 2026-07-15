"""Build a self-contained ReqPilot bundle for the current operating system.

The produced archive contains application source, the two ASR model folders,
and a wheelhouse for the Python/OS combination running this script. Build the
Windows bundle on Windows and the macOS bundle on the target Mac architecture;
Python wheels are platform-specific.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from src import config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = (
    ".env.example",
    ".gitignore",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "run_windows.bat",
    "run_mac.sh",
    "src",
    "scripts",
    "docs",
)


def _safe_remove(path: Path, allowed_parent: Path) -> None:
    resolved = path.resolve()
    parent = allowed_parent.resolve()
    if resolved == parent or parent not in resolved.parents:
        raise ValueError(f"refusing to remove path outside {parent}: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _copy_source(destination: Path) -> None:
    for relative in SOURCE_PATHS:
        source = PROJECT_ROOT / relative
        if not source.exists():
            continue
        target = destination / relative
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".pytest_cache", "data", "models",
                ),
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _copy_models(destination: Path) -> list[dict[str, object]]:
    model_root = destination / "models"
    model_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for label, source in (
        ("offline", config.OFFLINE_MODEL_DIR),
        ("streaming", config.STREAMING_MODEL_DIR),
    ):
        source = Path(source)
        if not source.is_dir():
            raise FileNotFoundError(
                f"{label} ASR model is missing at {source}; run scripts/fetch_models.py first"
            )
        target = model_root / source.name
        shutil.copytree(source, target)
        size = sum(item.stat().st_size for item in target.rglob("*") if item.is_file())
        records.append({"kind": label, "folder": source.name, "bytes": size})
    return records


def _download_wheels(destination: Path) -> None:
    requirement = PROJECT_ROOT / (
        "requirements-runtime.txt"
        if (PROJECT_ROOT / "requirements-runtime.txt").is_file()
        else "requirements.txt"
    )
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--dest",
            str(destination),
            "-r",
            str(requirement),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path, *, include_models: bool, include_wheels: bool) -> Path:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    build_parent = PROJECT_ROOT / "build" / "offline"
    build_parent.mkdir(parents=True, exist_ok=True)
    stage = build_parent / "ReqPilot"
    _safe_remove(stage, build_parent)
    stage.mkdir(parents=True)

    _copy_source(stage)
    models = _copy_models(stage) if include_models else []
    if include_wheels:
        _download_wheels(stage / "wheelhouse")

    manifest = {
        "product": "ReqPilot",
        "created_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "models": models,
        "wheelhouse": include_wheels,
        "install": (
            "Run run_windows.bat"
            if os.name == "nt"
            else "Make run_mac.sh executable and run it"
        ),
    }
    (stage / "OFFLINE_BUNDLE.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        archive_base = Path(temp) / output.stem
        archive = Path(shutil.make_archive(str(archive_base), "zip", stage.parent, stage.name))
        shutil.move(str(archive), output)
    manifest["archive_sha256"] = _sha256(output)
    print(json.dumps(manifest, indent=2))
    print(f"Bundle written to {output}")
    return output


def main() -> None:
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "dist" / f"ReqPilot-offline-{system}-{machine}.zip",
    )
    parser.add_argument("--without-models", action="store_true")
    parser.add_argument("--without-wheels", action="store_true")
    args = parser.parse_args()
    build(
        args.output,
        include_models=not args.without_models,
        include_wheels=not args.without_wheels,
    )


if __name__ == "__main__":
    main()
