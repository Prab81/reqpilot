import numpy as np

from src.audio.engine import AsrEngine


RATE = 16_000


class FakeDecoder:
    def __init__(self):
        self.samples = 0

    def reset(self):
        self.samples = 0

    def feed(self, samples):
        self.samples += len(samples)
        return "partial" if self.samples >= 3_200 else None

    def finalize(self):
        return f"final {self.samples}"


def tone(seconds: float) -> np.ndarray:
    t = np.arange(int(RATE * seconds), dtype=np.float32) / RATE
    return (0.04 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds), dtype=np.float32)


def test_continuous_audio_produces_ordered_partials_and_two_finals():
    partials = []
    finals = []
    engine = AsrEngine(lambda text, uid: partials.append((text, uid)), finals.append,
                       decoder=FakeDecoder())
    engine.feed(np.concatenate((silence(0.4), tone(0.6), silence(1.5),
                                tone(0.6), silence(1.0))))

    assert len(finals) == 2
    assert [u.id for u in finals] == [1, 2]
    assert finals[0].t0 < finals[0].t1 < finals[1].t0 < finals[1].t1
    assert any(uid == 1 for _text, uid in partials)
    assert any(uid == 2 for _text, uid in partials)


def test_flush_force_finalizes_current_utterance():
    finals = []
    engine = AsrEngine(lambda *_: None, finals.append, decoder=FakeDecoder())
    engine.feed(np.concatenate((silence(0.4), tone(0.5))))
    assert finals == []
    engine.flush()
    assert len(finals) == 1
    assert finals[0].text.startswith("final ")


def test_continuous_speech_is_hard_cut_without_a_timeline_gap():
    finals = []
    engine = AsrEngine(lambda *_: None, finals.append, decoder=FakeDecoder())
    engine.feed(np.concatenate((silence(0.4), tone(46.0), silence(1.0))))
    assert len(finals) == 2
    assert finals[0].t1 <= 45.5
    assert finals[1].t0 == finals[0].t1
    assert finals[1].t1 > finals[1].t0
