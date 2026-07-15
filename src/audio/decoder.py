"""Dual-model utterance decoder, adapted from InkVoice's proven ASR sidecar.

Zipformer incrementally produces live partials while Parakeet-TDT produces the
committed, punctuated text.  Offline decoding is deliberately bounded: live
InkVoice testing found that feeding this Parakeet model more than about twenty
seconds can silently degrade, so audio is decoded and stitched in chunks no
longer than 19 seconds.

Recognizer objects are injectable.  This keeps the chunking and orchestration
fully testable without loading ~800 MB of model weights.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from src import config

SAMPLE_RATE = 16_000
CHUNK_SOFT_TRIGGER_S = 15.0
CHUNK_HARD_MAX_S = 19.0
SILENCE_TAIL_S = 0.3
SILENCE_RMS_THRESHOLD = 0.015


def _sherpa() -> Any:
    # Import lazily so the web server and mock-driven tests can start without
    # native ASR wheels or models being installed.
    try:
        import sherpa_onnx
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "sherpa-onnx is required for live transcription; install requirements.txt"
        ) from exc
    return sherpa_onnx


def _required_files(model_dir: Path, names: tuple[str, ...], label: str) -> None:
    missing = [name for name in names if not (model_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"{label} model is incomplete at {model_dir}: missing {', '.join(missing)}. "
            "Run scripts/fetch_models.py or set the corresponding REQPILOT_*_MODEL_DIR."
        )


def build_offline_recognizer(model_dir: Path | str | None = None) -> Any:
    model_dir = Path(model_dir or config.OFFLINE_MODEL_DIR)
    names = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    _required_files(model_dir, names, "offline Parakeet")
    return _sherpa().OfflineRecognizer.from_transducer(
        encoder=str(model_dir / names[0]),
        decoder=str(model_dir / names[1]),
        joiner=str(model_dir / names[2]),
        tokens=str(model_dir / names[3]),
        num_threads=4,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        model_type="nemo_transducer",
    )


def build_streaming_recognizer(model_dir: Path | str | None = None) -> Any:
    model_dir = Path(model_dir or config.STREAMING_MODEL_DIR)
    names = (
        "encoder-epoch-99-avg-1.int8.onnx",
        "decoder-epoch-99-avg-1.int8.onnx",
        "joiner-epoch-99-avg-1.int8.onnx",
        "tokens.txt",
    )
    _required_files(model_dir, names, "streaming Zipformer")
    return _sherpa().OnlineRecognizer.from_transducer(
        encoder=str(model_dir / names[0]),
        decoder=str(model_dir / names[1]),
        joiner=str(model_dir / names[2]),
        tokens=str(model_dir / names[3]),
        num_threads=4,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
    )


def is_silence(samples: np.ndarray, threshold: float = SILENCE_RMS_THRESHOLD) -> bool:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return False
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) < threshold


class UtteranceDecoder:
    """One utterance at a time; call reset, feed repeatedly, then finalize."""

    def __init__(
        self,
        offline_recognizer: Any | None = None,
        streaming_recognizer: Any | None = None,
        *,
        sample_rate: int = SAMPLE_RATE,
        chunk_soft_s: float = CHUNK_SOFT_TRIGGER_S,
        chunk_hard_s: float = CHUNK_HARD_MAX_S,
        silence_tail_s: float = SILENCE_TAIL_S,
    ) -> None:
        self.offline_recognizer = offline_recognizer or build_offline_recognizer()
        self.streaming_recognizer = streaming_recognizer or build_streaming_recognizer()
        self.sample_rate = sample_rate
        self.chunk_soft_samples = int(chunk_soft_s * sample_rate)
        self.chunk_hard_samples = int(chunk_hard_s * sample_rate)
        self.silence_tail_samples = max(1, int(silence_tail_s * sample_rate))
        self.decoded_chunk_lengths: list[int] = []
        self.reset()

    def reset(self) -> None:
        self._chunk_buffer = np.zeros(0, dtype=np.float32)
        self._raw_chunks: list[str] = []
        self._online_stream = self.streaming_recognizer.create_stream()
        self._last_partial = ""

    def _decode_offline(self, samples: np.ndarray) -> str:
        stream = self.offline_recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, samples)
        self.offline_recognizer.decode_stream(stream)
        return str(stream.result.text).strip()

    def _flush_chunk(self) -> None:
        if self._chunk_buffer.size == 0:
            return
        chunk = self._chunk_buffer
        self._chunk_buffer = np.zeros(0, dtype=np.float32)
        self.decoded_chunk_lengths.append(int(chunk.size))
        text = self._decode_offline(chunk)
        if text:
            self._raw_chunks.append(text)

    def feed(self, samples: np.ndarray) -> str | None:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return None

        self._chunk_buffer = np.concatenate((self._chunk_buffer, samples))
        self._online_stream.accept_waveform(self.sample_rate, samples)
        while self.streaming_recognizer.is_ready(self._online_stream):
            self.streaming_recognizer.decode_stream(self._online_stream)
        partial = str(self.streaming_recognizer.get_result(self._online_stream)).strip()

        # A caller may feed an arbitrarily large WebSocket frame. Slice hard
        # chunks in a loop; never pass >19 seconds to Parakeet.
        while self._chunk_buffer.size >= self.chunk_hard_samples:
            head = self._chunk_buffer[: self.chunk_hard_samples]
            self._chunk_buffer = self._chunk_buffer[self.chunk_hard_samples :]
            saved = self._chunk_buffer
            self._chunk_buffer = head
            self._flush_chunk()
            self._chunk_buffer = saved

        if self._chunk_buffer.size >= self.chunk_soft_samples:
            tail = self._chunk_buffer[-self.silence_tail_samples :]
            if is_silence(tail):
                self._flush_chunk()

        if not partial or partial == self._last_partial:
            return None
        self._last_partial = partial
        return partial

    def finalize(self) -> str:
        self._flush_chunk()
        text = " ".join(self._raw_chunks).strip()
        if not text:
            text = self._last_partial
        # Parakeet supplies punctuation/casing; only normalize chunk-boundary
        # whitespace here so its output is otherwise preserved verbatim.
        text = " ".join(text.split())
        self.reset()
        return text
