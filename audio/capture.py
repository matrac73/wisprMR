"""Audio capture with ring buffer pre-roll for push-to-talk dictation."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from loguru import logger


class RingBuffer:
    """Thread-safe circular audio buffer for pre-roll capture."""

    def __init__(self, max_samples: int) -> None:
        self._buf: deque[np.ndarray] = deque()
        self._max_samples = max_samples
        self._total = 0
        self._lock = threading.Lock()

    def push(self, chunk: np.ndarray) -> None:
        with self._lock:
            self._buf.append(chunk.copy())
            self._total += len(chunk)
            while self._total > self._max_samples and self._buf:
                removed = self._buf.popleft()
                self._total -= len(removed)

    def snapshot(self) -> np.ndarray:
        with self._lock:
            if not self._buf:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(list(self._buf)).astype(np.float32)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._total = 0


class AudioCapture:
    """
    Continuously captures microphone audio into a ring buffer.

    On hotkey press, starts collecting live audio.
    On hotkey release, assembles pre-roll + live audio and returns it.
    """

    CHUNK_FRAMES = 512  # frames per sounddevice callback

    def __init__(
        self,
        sample_rate: int = 16000,
        preroll_ms: int = 500,
        max_record_s: float = 120.0,
        device: Optional[int | str] = None,
        rms_callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.preroll_frames = int(sample_rate * preroll_ms / 1000)
        self.max_record_frames = int(sample_rate * max_record_s)
        self.device = device
        self.rms_callback = rms_callback

        self._ring = RingBuffer(self.preroll_frames)
        self._live: list[np.ndarray] = []
        self._recording = False
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.debug("sounddevice status: {}", status)
        chunk = indata[:, 0].copy()  # mono

        # RMS for VU meter
        rms = float(np.sqrt(np.mean(chunk**2)))
        if self.rms_callback:
            try:
                self.rms_callback(rms)
            except Exception:
                pass

        with self._lock:
            if self._recording:
                self._live.append(chunk)
                live_total = sum(len(c) for c in self._live)
                if live_total >= self.max_record_frames:
                    logger.warning("Max recording duration reached, stopping capture.")
                    self._recording = False
            else:
                self._ring.push(chunk)

    def start_stream(self) -> None:
        """Open the sounddevice input stream (call once at startup)."""
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.CHUNK_FRAMES,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info("Audio stream started ({}Hz, device={})", self.sample_rate, self.device)

    def stop_stream(self) -> None:
        """Close the sounddevice stream."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def begin_recording(self) -> None:
        """Mark start of user recording (hotkey down)."""
        with self._lock:
            self._live = []
            self._recording = True
        logger.debug("Recording started.")

    def end_recording(self) -> np.ndarray:
        """
        Mark end of user recording (hotkey up).

        Returns:
            Float32 mono PCM at self.sample_rate, pre-roll prepended.
        """
        with self._lock:
            self._recording = False
            preroll = self._ring.snapshot()
            live = np.concatenate(self._live) if self._live else np.zeros(0, dtype=np.float32)
            self._ring.clear()

        audio = np.concatenate([preroll, live]).astype(np.float32)
        # Normalize to [-1, 1] (audio peut être vide si release sans begin)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1e-6:
            audio = audio / peak
        duration_s = len(audio) / self.sample_rate
        logger.debug("Recording ended: {:.2f}s ({} frames)", duration_s, len(audio))
        return audio

    def dump_wav(self, path: str) -> None:
        """Save the last captured audio to a WAV file (for testing)."""
        import wave, struct
        audio = self.end_recording()
        with wave.open(path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        logger.info("WAV saved to {}", path)
