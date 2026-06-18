"""Unit tests for StreamingSession segmentation (no real Whisper model)."""
import threading
import time

import numpy as np

from stt.streaming import StreamingSession

SR = 16000


class FakeTranscriber:
    """Records the segments handed to it and returns a deterministic label."""

    def __init__(self):
        self.language = None
        self.initial_prompt = None
        self.segments = []
        self._lock = threading.Lock()
        self._n = 0

    def transcribe_segment(self, audio):
        with self._lock:
            self.segments.append(len(audio) / SR)
            self._n += 1
            n = self._n
        # Loud segment → "wordN"; (near-)silent → "" (mimics VAD dropping it).
        if float(np.max(np.abs(audio))) < 0.02:
            return ""
        return f"word{n}"


def _voice(seconds, freq=200, amp=0.5):
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(seconds):
    return np.zeros(int(SR * seconds), dtype=np.float32)


def _feed_realtime(session, audio, step_s=0.1):
    """Feed audio in small steps, pausing like a real mic stream, so the
    background worker gets its 120ms ticks (as it would during recording)."""
    step = int(SR * step_s)
    for i in range(0, len(audio), step):
        session.feed(audio[i : i + step])
        time.sleep(step_s)


def test_commits_at_silence_and_keeps_tail_short():
    fake = FakeTranscriber()
    s = StreamingSession(fake, sample_rate=SR)
    s.start()
    # Two voiced bursts separated by a clear pause, then a short final tail,
    # fed in real time so the worker can commit during "recording".
    _feed_realtime(s, _voice(1.5))
    _feed_realtime(s, _silence(0.5))
    _feed_realtime(s, _voice(1.5))
    _feed_realtime(s, _silence(0.4))
    committed_before_finish = len(fake.segments)
    _feed_realtime(s, _voice(0.6))  # short tail
    text = s.finish()

    # Segments were committed *during* recording (streaming worked).
    assert committed_before_finish >= 1
    # Final transcript stitches the committed words together.
    assert "word" in text
    # The tail transcribed at finish() should be short (< the whole utterance).
    assert fake.segments[-1] < 2.0


def test_forced_commit_bounds_tail_without_pauses():
    fake = FakeTranscriber()
    s = StreamingSession(fake, sample_rate=SR, force_commit_s=2.0)
    s.start()
    # Continuous speech, no pause at all.
    s.feed(_voice(5.0))
    time.sleep(0.8)
    # A forced cut should have fired before we ever call finish().
    assert len(fake.segments) >= 1
    text = s.finish()
    assert text != ""


def test_short_clip_single_segment():
    fake = FakeTranscriber()
    s = StreamingSession(fake, sample_rate=SR)
    s.start()
    s.feed(_voice(0.5))
    text = s.finish()
    # Whole short clip handled in one go.
    assert text == "word1"


def test_cancel_does_not_transcribe_tail():
    fake = FakeTranscriber()
    s = StreamingSession(fake, sample_rate=SR)
    s.start()
    s.feed(_voice(0.5))
    s.cancel()
    assert fake.segments == []
