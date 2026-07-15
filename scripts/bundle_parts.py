"""Split and reassemble large ReqPilot offline archives with checksums."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split(source: Path, output_dir: Path, part_bytes: int) -> Path:
    source = source.resolve()
    output_dir = output_dir.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if part_bytes <= 0:
        raise ValueError("part size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    parts: list[dict[str, object]] = []
    with source.open("rb") as handle:
        index = 1
        while chunk := handle.read(part_bytes):
            part = output_dir / f"{source.name}.{index:03d}"
            part.write_bytes(chunk)
            parts.append({"file": part.name, "bytes": len(chunk), "sha256": sha256(part)})
            index += 1
    manifest = output_dir / f"{source.name}.parts.json"
    manifest.write_text(
        json.dumps(
            {
                "source": source.name,
                "bytes": source.stat().st_size,
                "sha256": sha256(source),
                "parts": parts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def reassemble(manifest: Path, output: Path | None = None) -> Path:
    manifest = manifest.resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    output = (output or manifest.parent / data["source"]).resolve()
    if output == manifest or output in [manifest.parent / p["file"] for p in data["parts"]]:
        raise ValueError("output would overwrite the manifest or an archive part")
    with output.open("wb") as target:
        for record in data["parts"]:
            part = manifest.parent / record["file"]
            if not part.is_file() or sha256(part) != record["sha256"]:
                raise ValueError(f"part is missing or corrupt: {part.name}")
            with part.open("rb") as handle:
                for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                    target.write(chunk)
    if output.stat().st_size != data["bytes"] or sha256(output) != data["sha256"]:
        output.unlink(missing_ok=True)
        raise ValueError("reassembled archive checksum does not match")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    split_parser = sub.add_parser("split")
    split_parser.add_argument("source", type=Path)
    split_parser.add_argument("--output-dir", type=Path)
    split_parser.add_argument("--part-mb", type=int, default=95)
    join_parser = sub.add_parser("reassemble")
    join_parser.add_argument("manifest", type=Path)
    join_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "split":
        directory = args.output_dir or args.source.parent / f"{args.source.name}-parts"
        print(split(args.source, directory, args.part_mb * 1024 * 1024))
    else:
        print(reassemble(args.manifest, args.output))


if __name__ == "__main__":
    main()
