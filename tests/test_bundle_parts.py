from pathlib import Path

import pytest

from scripts.bundle_parts import reassemble, split


def test_split_and_reassemble_round_trip(tmp_path: Path):
    source = tmp_path / "bundle.zip"
    source.write_bytes(bytes(range(256)) * 25)
    manifest = split(source, tmp_path / "parts", 777)
    source.unlink()
    rebuilt = reassemble(manifest, tmp_path / "rebuilt.zip")
    assert rebuilt.read_bytes() == bytes(range(256)) * 25


def test_reassemble_detects_corrupt_part(tmp_path: Path):
    source = tmp_path / "bundle.zip"
    source.write_bytes(b"reqpilot" * 100)
    manifest = split(source, tmp_path / "parts", 101)
    part = tmp_path / "parts" / "bundle.zip.001"
    part.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="missing or corrupt"):
        reassemble(manifest, tmp_path / "rebuilt.zip")
