import numpy as np
import pytest

from src.audio.vad import EnergyVAD, SegmentAudio, SegmentClose, SegmentOpen


RATE = 16_000


def tone(seconds: float, amplitude: float = 0.04) -> np.ndarray:
    t = np.arange(int(RATE * seconds), dtype=np.float32) / RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds), dtype=np.float32)


def test_silence_speech_silence_emits_one_segment_with_preroll_and_hangover():
    events = []
    vad = EnergyVAD(events.append)
    vad.process(np.concatenate((silence(0.5), tone(0.5), silence(1.0))))

    opens = [e for e in events if isinstance(e, SegmentOpen)]
    closes = [e for e in events if isinstance(e, SegmentClose)]
    audio = np.concatenate([e.samples for e in events if isinstance(e, SegmentAudio)])

    assert len(opens) == len(closes) == 1
    assert opens[0].t0 == pytest.approx(0.24, abs=0.03)
    assert closes[0].reason == "silence"
    assert audio.size / RATE >= 1.5  # 300 ms pre-roll + speech + ~800 ms hangover


def test_half_second_pause_stays_inside_one_utterance():
    events = []
    vad = EnergyVAD(events.append)
    vad.process(np.concatenate((silence(0.4), tone(0.5), silence(0.5), tone(0.5), silence(1.0))))
    assert sum(isinstance(e, SegmentOpen) for e in events) == 1
    assert sum(isinstance(e, SegmentClose) for e in events) == 1


def test_flush_closes_open_segment_and_keeps_partial_frame():
    events = []
    vad = EnergyVAD(events.append)
    vad.process(np.concatenate((silence(0.4), tone(0.4), np.ones(7, dtype=np.float32) * 0.02)))
    vad.flush()
    closes = [e for e in events if isinstance(e, SegmentClose)]
    assert closes[-1].reason == "flush"
