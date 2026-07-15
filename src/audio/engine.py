"""Thread-safe orchestration of continuous VAD and dual-model ASR."""
from __future__ import annotations

from collections.abc import Callable
from threading import RLock

import numpy as np

from src.audio.decoder import UtteranceDecoder
from src.audio.vad import EnergyVAD, SegmentAudio, SegmentClose, SegmentOpen, VadEvent
from src.intelligence.state import Utterance


class AsrEngine:
    def __init__(
        self,
        on_partial: Callable[[str, int], None],
        on_final: Callable[[Utterance], None],
        *,
        decoder: UtteranceDecoder | None = None,
        vad_factory: Callable[[Callable[[VadEvent], None]], EnergyVAD] | None = None,
    ) -> None:
        self._on_partial = on_partial
        self._on_final = on_final
        self._decoder = decoder or UtteranceDecoder()
        self._lock = RLock()
        self._next_id = 1
        self._current_id: int | None = None
        self._t0 = 0.0
        factory = vad_factory or (lambda callback: EnergyVAD(callback))
        self._vad = factory(self._on_vad_event)

    def feed(self, pcm: np.ndarray) -> None:
        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return
        with self._lock:
            self._vad.process(pcm)

    def flush(self) -> None:
        with self._lock:
            self._vad.flush()

    def _on_vad_event(self, event: VadEvent) -> None:
        if isinstance(event, SegmentOpen):
            self._decoder.reset()
            self._current_id = self._next_id
            self._next_id += 1
            self._t0 = event.t0
            return
        if isinstance(event, SegmentAudio):
            if self._current_id is None:
                return
            partial = self._decoder.feed(event.samples)
            if partial:
                self._on_partial(partial, self._current_id)
            return
        if isinstance(event, SegmentClose) and self._current_id is not None:
            utterance_id = self._current_id
            text = self._decoder.finalize()
            self._current_id = None
            self._on_final(Utterance(
                id=utterance_id,
                t0=self._t0,
                t1=max(self._t0, event.t1),
                text=text,
            ))
