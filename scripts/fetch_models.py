"""Fetch ReqPilot's public sherpa-onnx ASR models when they are absent.

The launcher calls this on every start; it is a fast no-op when either the
configured InkVoice model directories or local model copies are complete.
"""
from __future__ import annotations

import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

from src import config

MODELS_DIR = config.PROJECT_ROOT / "models"
RELEASE_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

JOBS = (
    {
        "name": "Parakeet (accurate finals)",
        "configured": config.OFFLINE_MODEL_DIR,
        "archive": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2",
        "folder": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        "files": ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"),
    },
    {
        "name": "Zipformer (live partials)",
        "configured": config.STREAMING_MODEL_DIR,
        "archive": "sherpa-onnx-streaming-zipformer-en-2023-06-21.tar.bz2",
        "folder": "sherpa-onnx-streaming-zipformer-en-2023-06-21",
        "files": (
            "encoder-epoch-99-avg-1.int8.onnx",
            "decoder-epoch-99-avg-1.int8.onnx",
            "joiner-epoch-99-avg-1.int8.onnx",
            "tokens.txt",
        ),
    },
)


def complete(path: Path, files: tuple[str, ...]) -> bool:
    return all((path / name).is_file() for name in files)


def progress(block: int, block_size: int, total: int) -> None:
    if total > 0:
        done = min(block * block_size, total)
        print(f"\r  {done * 100 // total:3d}% ({done // 1_048_576}/{total // 1_048_576} MB)",
              end="", flush=True)


def fetch(job: dict) -> None:
    configured = Path(job["configured"])
    if complete(configured, job["files"]):
        print(f"[ready] {job['name']}: {configured}")
        return

    destination = MODELS_DIR / job["folder"]
    if complete(destination, job["files"]):
        print(f"[ready] {job['name']}: {destination}")
        return

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    archive = MODELS_DIR / job["archive"]
    temporary = MODELS_DIR / "_extract_tmp"
    url = f"{RELEASE_BASE}/{job['archive']}"
    try:
        print(f"[fetch] {job['name']}\n  {url}")
        urllib.request.urlretrieve(url, archive, progress)
        print("\n  extracting...")
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.mkdir()
        with tarfile.open(archive, "r:bz2") as bundle:
            bundle.extractall(temporary, filter="data")
        source = temporary / job["folder"]
        destination.mkdir(parents=True, exist_ok=True)
        for name in job["files"]:
            shutil.copy2(source / name, destination / name)
        print(f"  ready: {destination}")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        archive.unlink(missing_ok=True)


def main() -> None:
    for job in JOBS:
        fetch(job)
    print("All ASR models are ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # top-level CLI: present one actionable error
        print(f"Model preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
