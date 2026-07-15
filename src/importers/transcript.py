"""Normalize pasted text, TXT, Teams WebVTT, and DOCX into utterances.

Speaker attribution is intentionally represented as a ``Speaker: text`` prefix:
``Utterance`` is the live-ASR wire/storage contract and has no separate speaker
field.  Keeping the prefix means imported and live transcripts can use the same
intelligence, evidence, BRD, and delivery pipeline without a schema fork.
"""
from __future__ import annotations

import html
import io
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.intelligence.state import Utterance

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_DOCX_ENTRIES = 2_000
ALLOWED_EXTENSIONS = {".txt", ".vtt", ".docx"}


class TranscriptImportError(ValueError):
    """A safe, user-facing transcript validation or parsing failure."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ImportResult:
    filename: str
    format: str
    utterances: list[Utterance]


@dataclass(slots=True)
class _Record:
    text: str
    t0: float | None = None
    t1: float | None = None


_TIMESTAMP = r"(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_CUE_RE = re.compile(
    rf"^\s*(?P<start>{_TIMESTAMP})\s*-->\s*(?P<end>{_TIMESTAMP})(?:\s+.*)?$"
)
_START_TIME_RE = re.compile(
    rf"^\s*[\[(]?(?P<time>{_TIMESTAMP})[\])]?\s*(?:[-|:]\s*)?(?P<rest>.*)$"
)
_TRAILING_TIME_RE = re.compile(rf"(?P<time>{_TIMESTAMP})\s*$")
_SPEAKER_TIME_RE = re.compile(
    rf"^\s*(?P<speaker>[^:\r\n]{{1,100}}?)\s*[\[(]?(?P<time>{_TIMESTAMP})[\])]?\s*:?[ \t]*(?P<rest>.*)$"
)
_SPEAKER_RE = re.compile(r"^\s*(?P<speaker>[^:\r\n]{1,100}):\s*(?P<rest>.*)$")
_VTT_VOICE_RE = re.compile(r"^\s*<v(?:\.[^ >]+)?\s+([^>]+)>(.*)$", re.I | re.S)
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_import_filename(filename: str) -> tuple[str, str]:
    """Return a safe basename and extension; reject paths and unsupported types."""
    if not isinstance(filename, str):
        raise TranscriptImportError("filename must be a string", status_code=400)
    clean = filename.strip()
    if not clean or len(clean) > 255 or "\x00" in clean:
        raise TranscriptImportError("filename is empty or too long", status_code=400)
    if ("/" in clean or "\\" in clean or ":" in clean or clean in {".", ".."}
            or ".." in Path(clean).parts):
        raise TranscriptImportError("filename must not contain a path", status_code=400)
    extension = Path(clean).suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        supported = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise TranscriptImportError(
            f"unsupported transcript type {extension or '(none)'}; expected {supported}",
            status_code=415,
        )
    return clean, extension


def import_transcript(content: bytes | str, filename: str) -> ImportResult:
    """Parse a complete transcript payload based on its safe filename extension."""
    safe_name, extension = validate_import_filename(filename)
    byte_size = len(content.encode("utf-8")) if isinstance(content, str) else len(content)
    if byte_size > MAX_IMPORT_BYTES:
        raise TranscriptImportError(
            f"transcript exceeds the {MAX_IMPORT_BYTES // (1024 * 1024)} MiB limit",
            status_code=413,
        )
    if byte_size == 0:
        raise TranscriptImportError("transcript is empty")

    if extension == ".docx":
        if isinstance(content, str):
            raise TranscriptImportError("DOCX imports must be uploaded as a file", status_code=400)
        text = _extract_docx(content)
        records = _parse_plain_text(text)
        kind = "docx"
    else:
        text = content if isinstance(content, str) else _decode_text(content)
        if extension == ".vtt":
            records = _parse_vtt(text)
            kind = "vtt"
        else:
            records = _parse_plain_text(text)
            kind = "txt"

    utterances = _records_to_utterances(records)
    if not utterances:
        raise TranscriptImportError("transcript contains no readable utterances")
    return ImportResult(filename=safe_name, format=kind, utterances=utterances)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise TranscriptImportError("transcript is not valid UTF-8, UTF-16, or Windows text")


def _clean_text(value: str) -> str:
    value = html.unescape(value.replace("\ufeff", ""))
    value = _CONTROL_RE.sub("", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _parse_time(value: str) -> float:
    pieces = value.replace(",", ".").split(":")
    try:
        if len(pieces) == 3:
            hours, minutes, seconds = pieces
        elif len(pieces) == 2:
            hours, minutes, seconds = "0", pieces[0], pieces[1]
        else:  # protected by the regex, kept defensive for direct calls
            raise ValueError
        minute_value, second_value = int(minutes), float(seconds)
        if second_value >= 60 or (len(pieces) == 3 and minute_value >= 60):
            raise ValueError
        result = int(hours) * 3600 + minute_value * 60 + second_value
    except ValueError as exc:
        raise TranscriptImportError(f"invalid timestamp {value!r}") from exc
    if not math.isfinite(result) or result < 0:
        raise TranscriptImportError(f"invalid timestamp {value!r}")
    return result


def _parse_vtt(source: str) -> list[_Record]:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    records: list[_Record] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.upper() == "WEBVTT":
            index += 1
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue

        cue = _CUE_RE.match(line)
        if cue is None and index + 1 < len(lines):
            # WebVTT permits an arbitrary cue identifier before the timing line.
            possible = _CUE_RE.match(lines[index + 1].strip())
            if possible is not None:
                index += 1
                cue = possible
        if cue is None:
            index += 1
            continue

        start = _parse_time(cue.group("start"))
        end = _parse_time(cue.group("end"))
        if end < start:
            raise TranscriptImportError("WebVTT cue end precedes its start")
        index += 1
        payload: list[str] = []
        while index < len(lines) and lines[index].strip():
            payload.append(lines[index].strip())
            index += 1
        text = " ".join(payload)
        voice = _VTT_VOICE_RE.match(text)
        speaker = ""
        if voice:
            speaker = _clean_text(voice.group(1))
            text = voice.group(2)
        text = _clean_text(_HTML_TAG_RE.sub("", text))
        if not speaker:
            match = _SPEAKER_RE.match(text)
            if match:
                speaker = _clean_text(match.group("speaker"))
                text = _clean_text(match.group("rest"))
        if text:
            records.append(_Record(_with_speaker(speaker, text), start, end))
    return records


def _parse_plain_text(source: str) -> list[_Record]:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    records: list[_Record] = []
    current_lines: list[str] = []
    current_speaker = ""
    current_t0: float | None = None
    current_t1: float | None = None

    def flush() -> None:
        nonlocal current_lines, current_speaker, current_t0, current_t1
        text = _clean_text(" ".join(current_lines))
        if text:
            records.append(_Record(_with_speaker(current_speaker, text), current_t0, current_t1))
        current_lines = []
        current_speaker = ""
        current_t0 = None
        current_t1 = None

    index = 0
    while index < len(lines):
        raw = lines[index]
        line = _clean_text(raw)
        if not line:
            flush()
            index += 1
            continue

        cue = _CUE_RE.match(line)
        if cue:
            flush()
            current_t0 = _parse_time(cue.group("start"))
            current_t1 = _parse_time(cue.group("end"))
            index += 1
            continue

        # Teams/Copilot exports often use "Speaker Name 0:05" as a turn header.
        speaker_time = _SPEAKER_TIME_RE.match(line)
        if speaker_time and _looks_like_speaker(speaker_time.group("speaker")):
            flush()
            current_speaker = _clean_text(speaker_time.group("speaker"))
            current_t0 = _parse_time(speaker_time.group("time"))
            rest = _clean_text(speaker_time.group("rest"))
            if rest:
                current_lines.append(rest)
            index += 1
            continue

        start_time = _START_TIME_RE.match(line)
        if start_time:
            flush()
            current_t0 = _parse_time(start_time.group("time"))
            rest = _clean_text(start_time.group("rest"))
            speaker_line = _SPEAKER_RE.match(rest)
            if speaker_line:
                current_speaker = _clean_text(speaker_line.group("speaker"))
                rest = _clean_text(speaker_line.group("rest"))
            if rest:
                current_lines.append(rest)
            index += 1
            continue

        speaker_line = _SPEAKER_RE.match(line)
        if speaker_line and _looks_like_speaker(speaker_line.group("speaker")):
            flush()
            current_speaker = _clean_text(speaker_line.group("speaker"))
            rest = _clean_text(speaker_line.group("rest"))
            if rest:
                current_lines.append(rest)
            index += 1
            continue

        # Alternate Teams copy format: speaker line, timestamp line, then words.
        if (not current_lines and index + 1 < len(lines)
                and _looks_like_speaker(line)):
            next_line = _clean_text(lines[index + 1])
            next_time = _START_TIME_RE.match(next_line)
            trailing_time = _TRAILING_TIME_RE.search(next_line)
            if ((next_time and not next_time.group("rest")) or trailing_time):
                flush()
                current_speaker = line
                current_t0 = _parse_time(
                    next_time.group("time") if next_time else trailing_time.group("time")
                )
                index += 2
                continue

        current_lines.append(line)
        index += 1
    flush()
    return records


def _looks_like_speaker(value: str) -> bool:
    clean = _clean_text(value)
    if not clean or len(clean.split()) > 10:
        return False
    # Avoid interpreting ordinary prose ending in a timestamp as a speaker name.
    return not clean.endswith(('.', '!', '?', ';')) and any(ch.isalpha() for ch in clean)


def _with_speaker(speaker: str, text: str) -> str:
    speaker, text = _clean_text(speaker), _clean_text(text)
    return f"{speaker}: {text}" if speaker else text


def _estimated_duration(text: str) -> float:
    # A deterministic speaking-rate estimate for traceability in untimed text.
    return max(1.0, min(30.0, len(text.split()) / 2.5))


def _records_to_utterances(records: Iterable[_Record]) -> list[Utterance]:
    source = [record for record in records if _clean_text(record.text)]
    out: list[Utterance] = []
    cursor = 0.0
    for index, record in enumerate(source, start=1):
        t0 = record.t0 if record.t0 is not None else cursor
        estimate = _estimated_duration(record.text)
        t1 = record.t1 if record.t1 is not None else t0 + estimate
        if t1 < t0:
            t1 = t0
        out.append(Utterance(index, float(t0), float(t1), _clean_text(record.text)))
        cursor = max(cursor, t1 + 0.25)
    return out


def _extract_docx(content: bytes) -> str:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise TranscriptImportError("file is not a valid DOCX document")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise TranscriptImportError("DOCX contains too many archive entries")
            total = 0
            for entry in entries:
                parts = Path(entry.filename.replace("\\", "/")).parts
                if entry.flag_bits & 0x1 or entry.filename.startswith(("/", "\\")) or ".." in parts:
                    raise TranscriptImportError("DOCX contains an unsafe archive entry")
                total += entry.file_size
                if total > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise TranscriptImportError("DOCX expands beyond the safe size limit", status_code=413)
            if "word/document.xml" not in archive.namelist():
                raise TranscriptImportError("file is not a Word DOCX document")
    except (zipfile.BadZipFile, OSError) as exc:
        raise TranscriptImportError("file is not a readable DOCX document") from exc

    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover - packaging/configuration failure
        raise RuntimeError("python-docx is required for DOCX transcript imports") from exc

    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise TranscriptImportError("file is not a readable DOCX document") from exc

    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            text = Paragraph(child, document).text.strip()
            if text:
                blocks.append(text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [_clean_text(cell.text.replace("\n", " ")) for cell in row.cells]
                cells = [cell for cell in cells if cell]
                if cells:
                    blocks.append(_docx_table_row(cells))
    # Word/Teams exports commonly use adjacent paragraphs for
    # ``speaker + timestamp`` followed by the spoken text.  A single newline
    # preserves that relationship; explicit speaker headers still split turns.
    return "\n".join(blocks)


def _docx_table_row(cells: list[str]) -> str:
    """Turn common 2/3-column Word transcript rows into a parseable turn."""
    if len(cells) == 2:
        return f"{cells[0]}: {cells[1]}"
    time_index = next(
        (index for index, value in enumerate(cells)
         if re.fullmatch(rf"[\[(]?{_TIMESTAMP}[\])]?,?", value)),
        None,
    )
    if time_index is not None:
        timestamp = _TRAILING_TIME_RE.search(cells[time_index].rstrip(","))
        others = [value for index, value in enumerate(cells) if index != time_index]
        if timestamp and len(others) >= 2:
            return f"{timestamp.group('time')} {others[0]}: {' '.join(others[1:])}"
    return " | ".join(cells)
