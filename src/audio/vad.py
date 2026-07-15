"""Energy-based VAD: segments a CONTINUOUS audio stream into utterances.

InkVoice was push-to-talk — the shell told the sidecar exactly where an
utterance began and ended. ReqPilot listens to an open meeting mic, so
segmentation must be inferred from the audio itself:

- 300 ms pre-roll: onset detection always lags the true speech start by a
  frame or two; replaying a short ring buffer into the segment keeps the
  first word's leading consonant (without it, finals reliably lose it).
- 800 ms hangover: natural mid-sentence pauses (breaths, commas) run
  300-600 ms; closing on them would shatter sentences into fragments that
  decode worse and read worse in the transcript pane.
- 45 s hard max per utterance, preferring a silence cut after 30 s: bounds
  worst-case final latency and keeps segments comfortably inside the
  decoder's chunked path; cutting at a detected pause avoids splitting a
  word across two utterances. A hard cut mid-speech immediately reopens a
  new segment so no audio is dropped.

The per-frame decision logic lives in small pure functions (frame_rms,
is_speech, updated_noise_floor); EnergyVAD is a thin state machine over
them, driven sample-array-in / events-out so it is unit-testable with
synthetic arrays and has no audio-backend or model dependencies.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SegmentOpen:
    t0: float  # session-relative seconds; includes the pre-roll


@dataclass(frozen=True)
class SegmentAudio:
    samples: np.ndarray  # float32 mono


@dataclass(frozen=True)
class SegmentClose:
    t1: float  # session-relative seconds at the close point
    reason: str  # "silence" | "max_duration" | "flush"


VadEvent = SegmentOpen | SegmentAudio | SegmentClose


def frame_rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def is_speech(rms: float, noise_floor: float, *, min_threshold: float, noise_ratio: float) -> bool:
    return rms >= max(min_threshold, noise_floor * noise_ratio)


def updated_noise_floor(noise_floor: float, rms: float, *, alpha: float) -> float:
    return (1.0 - alpha) * noise_floor + alpha * rms


class EnergyVAD:
    """Feed float32 mono PCM via process(); receives VadEvents on a callback.

    Not thread-safe by design — the caller (AsrEngine.feed) serializes access.
    """

    def __init__(
        self,
        on_event: Callable[[VadEvent], None],
        *,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        pre_roll_s: float = 0.3,
        hangover_s: float = 0.8,
        max_utterance_s: float = 45.0,
        prefer_cut_after_s: float = 30.0,
        long_cut_silence_s: float = 0.3,
        open_speech_frames: int = 3,
        min_threshold: float = 0.005,
        noise_ratio: float = 3.0,
        initial_noise_floor: float = 0.001,
        noise_alpha: float = 0.05,
        noise_rise_alpha: float = 0.0002,
    ) -> None:
        self._on_event = on_event
        self._rate = sample_rate
        self._frame_len = int(sample_rate * frame_ms / 1000)
        self._pre_roll_frames = max(1, round(pre_roll_s * 1000 / frame_ms))
        self._hangover_frames = max(1, round(hangover_s * 1000 / frame_ms))
        self._long_cut_silence_frames = max(1, round(long_cut_silence_s * 1000 / frame_ms))
        self._max_utt_samples = int(max_utterance_s * sample_rate)
        self._prefer_cut_samples = int(prefer_cut_after_s * sample_rate)
        # Requiring a few consecutive speech frames before opening rejects
        # single-frame clicks/pops; the pre-roll ring replays those frames
        # into the segment so nothing is lost by waiting.
        self._open_speech_frames = max(1, open_speech_frames)
        self._min_threshold = min_threshold
        self._noise_ratio = noise_ratio
        self._noise_alpha = noise_alpha
        # Very slow upward adaptation applied on speech-classified frames
        # outside a segment: recovers from a noise floor stuck low when the
        # room noise level rises persistently (otherwise constant fan/AC
        # noise above min_threshold would open segments forever).
        self._noise_rise_alpha = noise_rise_alpha

        self._noise_floor = initial_noise_floor
        self._pending = np.zeros(0, dtype=np.float32)
        self._pre_roll: deque[np.ndarray] = deque(maxlen=self._pre_roll_frames)
        self._consumed = 0  # total samples framed so far == session clock
        self._in_segment = False
        self._seg_emitted = 0  # samples emitted into the current segment
        self._silence_run = 0  # consecutive non-speech frames inside segment
        self._speech_run = 0  # consecutive speech frames outside segment

    # -- public API ---------------------------------------------------------

    def process(self, samples: np.ndarray) -> None:
        """Consume any-size float32 PCM; emits events via the callback."""
        samples = np.asarray(samples, dtype=np.float32)
        buf = np.concatenate([self._pending, samples]) if self._pending.size else samples
        fl = self._frame_len
        n_frames = buf.size // fl
        for i in range(n_frames):
            self._step(buf[i * fl:(i + 1) * fl])
        self._pending = buf[n_frames * fl:]

    def flush(self) -> None:
        """Force-close any open segment (session stop / engine flush)."""
        if self._in_segment:
            if self._pending.size:
                self._consumed += self._pending.size
                self._emit_audio(self._pending)
            self._close("flush")
        else:
            self._consumed += self._pending.size
        self._pending = np.zeros(0, dtype=np.float32)

    @property
    def in_segment(self) -> bool:
        return self._in_segment

    # -- internals ----------------------------------------------------------

    def _step(self, frame: np.ndarray) -> None:
        rms = frame_rms(frame)
        speech = is_speech(rms, self._noise_floor,
                           min_threshold=self._min_threshold, noise_ratio=self._noise_ratio)
        self._consumed += frame.size

        if not speech:
            self._noise_floor = updated_noise_floor(self._noise_floor, rms, alpha=self._noise_alpha)

        if not self._in_segment:
            if speech:
                self._speech_run += 1
                self._noise_floor = updated_noise_floor(
                    self._noise_floor, rms, alpha=self._noise_rise_alpha)
                if self._speech_run >= self._open_speech_frames:
                    # Pre-roll already contains the onset frames (incl. this
                    # run) — open at the earliest buffered sample.
                    self._pre_roll.append(frame)
                    pre = list(self._pre_roll)
                    pre_len = sum(p.size for p in pre)
                    self._open(self._consumed - pre_len)
                    for p in pre:
                        self._emit_audio(p)
                    self._pre_roll.clear()
                    return
            else:
                self._speech_run = 0
            self._pre_roll.append(frame)
            return

        # inside a segment
        self._emit_audio(frame)
        self._silence_run = 0 if speech else self._silence_run + 1

        if self._seg_emitted >= self._max_utt_samples:
            self._close("max_duration")
            if speech:
                # Mid-speech hard cut: reopen immediately so no audio drops
                # between consecutive segments (TS-002-04).
                self._open(self._consumed)
            return

        if not speech:
            long_utterance = self._seg_emitted >= self._prefer_cut_samples
            if self._silence_run >= self._hangover_frames or (
                    long_utterance and self._silence_run >= self._long_cut_silence_frames):
                self._close("silence")

    def _open(self, start_sample: int) -> None:
        self._in_segment = True
        self._seg_emitted = 0
        self._silence_run = 0
        self._speech_run = 0
        self._on_event(SegmentOpen(t0=max(0, start_sample) / self._rate))

    def _emit_audio(self, samples: np.ndarray) -> None:
        self._seg_emitted += samples.size
        self._on_event(SegmentAudio(samples=samples))

    def _close(self, reason: str) -> None:
        self._in_segment = False
        self._silence_run = 0
        self._speech_run = 0
        self._pre_roll.clear()
        self._on_event(SegmentClose(t1=self._consumed / self._rate, reason=reason))
