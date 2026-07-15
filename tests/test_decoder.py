import os
from difflib import SequenceMatcher

import numpy as np
import pytest

from src.audio.decoder import UtteranceDecoder


class OfflineStream:
    def __init__(self):
        self.samples = np.zeros(0, dtype=np.float32)
        self.result = type("Result", (), {"text": ""})()

    def accept_waveform(self, _rate, samples):
        self.samples = np.asarray(samples)


class FakeOfflineRecognizer:
    def __init__(self):
        self.inputs = []

    def create_stream(self):
        return OfflineStream()

    def decode_stream(self, stream):
        self.inputs.append(stream.samples.copy())
        stream.result.text = f"chunk{len(self.inputs)}"


class OnlineStream:
    def __init__(self):
        self.samples = 0

    def accept_waveform(self, _rate, samples):
        self.samples += len(samples)


class FakeOnlineRecognizer:
    def create_stream(self):
        return OnlineStream()

    def is_ready(self, _stream):
        return False

    def decode_stream(self, _stream):
        raise AssertionError("not ready")

    def get_result(self, stream):
        return "live words" if stream.samples else ""


def make_decoder(**kwargs):
    offline = FakeOfflineRecognizer()
    decoder = UtteranceDecoder(offline, FakeOnlineRecognizer(), **kwargs)
    return decoder, offline


def test_partial_is_only_returned_when_nonempty_and_changed():
    decoder, _offline = make_decoder()
    assert decoder.feed(np.ones(1600, dtype=np.float32) * 0.02) == "live words"
    assert decoder.feed(np.ones(1600, dtype=np.float32) * 0.02) is None


def test_thirty_seconds_is_decoded_in_multiple_chunks_all_at_most_nineteen_seconds():
    decoder, offline = make_decoder()
    decoder.feed(np.ones(30 * 16_000, dtype=np.float32) * 0.02)
    text = decoder.finalize()
    assert len(offline.inputs) >= 2
    assert max(map(len, offline.inputs)) <= 19 * 16_000
    assert text == "chunk1 chunk2"


def test_soft_boundary_flushes_during_silence():
    decoder, offline = make_decoder(chunk_soft_s=1.0, chunk_hard_s=2.0)
    decoder.feed(np.concatenate((np.ones(14_000, dtype=np.float32) * 0.02,
                                 np.zeros(4_000, dtype=np.float32))))
    assert len(offline.inputs) == 1
    assert decoder.finalize() == "chunk1"


@pytest.mark.skipif(os.environ.get("REQPILOT_REAL_ASR_TEST") != "1",
                    reason="set REQPILOT_REAL_ASR_TEST=1 to load the local 800 MB ASR models")
def test_real_models_decode_known_english_fixture():
    import soundfile as sf

    from src import config
    from src.audio.decoder import build_offline_recognizer, build_streaming_recognizer

    wav = config.OFFLINE_MODEL_DIR / "test_wavs" / "en.wav"
    if not wav.is_file():
        pytest.skip(f"model fixture is not installed: {wav}")
    samples, sample_rate = sf.read(wav, dtype="float32")
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    source_t = np.arange(len(samples)) / sample_rate
    target_t = np.arange(round(len(samples) * 16_000 / sample_rate)) / 16_000
    samples = np.interp(target_t, source_t, samples).astype(np.float32)

    decoder = UtteranceDecoder(build_offline_recognizer(), build_streaming_recognizer())
    for start in range(0, samples.size, 1_600):
        decoder.feed(samples[start : start + 1_600])
    actual = decoder.finalize().lower()
    expected = "ask not what your country can do for you ask what you can do for your country"
    assert SequenceMatcher(None, actual, expected).ratio() >= 0.8
