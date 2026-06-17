"""Unit tests for audio.capture (ring buffer logic, no sounddevice)."""
from __future__ import annotations

import numpy as np
import pytest

from audio.capture import RingBuffer, AudioCapture


def test_ring_buffer_size_limit():
    buf = RingBuffer(max_samples=100)
    buf.push(np.ones(60, dtype=np.float32))
    buf.push(np.ones(60, dtype=np.float32))
    snap = buf.snapshot()
    # Should keep only the last 100 samples
    assert len(snap) <= 100


def test_ring_buffer_clear():
    buf = RingBuffer(max_samples=500)
    buf.push(np.ones(100, dtype=np.float32))
    buf.clear()
    snap = buf.snapshot()
    assert len(snap) == 0


def test_ring_buffer_empty_snapshot():
    buf = RingBuffer(max_samples=500)
    snap = buf.snapshot()
    assert len(snap) == 0


def test_audio_capture_end_without_begin():
    """end_recording() before begin_recording() returns empty/zeros."""
    cap = AudioCapture(sample_rate=16000, preroll_ms=100)
    audio = cap.end_recording()
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32


def test_audio_capture_normalization():
    """Audio returned by end_recording() is normalised to [-1, 1]."""
    import unittest.mock as mock
    cap = AudioCapture(sample_rate=16000, preroll_ms=0)
    # Manually inject large-amplitude live data
    cap._live = [np.array([0.0, 5000.0, -3000.0], dtype=np.float32)]
    cap._recording = False
    audio = cap.end_recording()
    assert np.max(np.abs(audio)) <= 1.0 + 1e-6
