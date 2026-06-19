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

    A background watchdog keeps the stream bound to the current Windows default
    input device: PortAudio resolves ``device=None`` only once (at stream open)
    and never follows later default-device changes or hot-plug events, so the
    watchdog detects those and transparently rebuilds the stream.
    """

    CHUNK_FRAMES = 512  # frames per sounddevice callback
    MONITOR_INTERVAL_S = 1.0  # how often the watchdog checks the input device
    SAFETY_RESYNC_S = 5.0  # force a PortAudio re-init this often (catches silent
    #                        default switches that a cheap query can't see)

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
        # Optional consumer fed every live chunk during recording (streaming STT).
        self._live_consumer: Optional[Callable[[np.ndarray], None]] = None

        # Device watchdog state.
        self._rebuild_lock = threading.RLock()
        self._active_device_name: Optional[str] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._last_resync = 0.0
        self._warned_no_device = False

    def set_live_consumer(
        self, consumer: Optional[Callable[[np.ndarray], None]]
    ) -> None:
        """Register/clear a callback fed each live audio chunk while recording."""
        with self._lock:
            self._live_consumer = consumer

    def preroll_snapshot(self) -> np.ndarray:
        """Current pre-roll buffer contents (audio captured just before press)."""
        return self._ring.snapshot()

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
            recording = self._recording
            consumer = self._live_consumer
            if recording:
                self._live.append(chunk)
                live_total = sum(len(c) for c in self._live)
                if live_total >= self.max_record_frames:
                    logger.warning("Max recording duration reached, stopping capture.")
                    self._recording = False
            else:
                self._ring.push(chunk)

        # Feed the streaming consumer outside the lock (it has its own).
        if recording and consumer is not None:
            try:
                consumer(chunk)
            except Exception:
                pass

    def start_stream(self) -> None:
        """Open the sounddevice input stream and start the device watchdog."""
        with self._rebuild_lock:
            if self._stream is None:
                self._open_stream_locked()
        self._start_monitor()

    def stop_stream(self) -> None:
        """Stop the watchdog and close the sounddevice stream."""
        self._monitor_stop.set()
        thread = self._monitor_thread
        self._monitor_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._rebuild_lock:
            self._close_stream_locked()

    # ------------------------------------------------------------------
    # Device watchdog — follow the current Windows default input device
    # ------------------------------------------------------------------

    def _resolve_input_name(self) -> Optional[str]:
        """Name of the device the stream resolves to (cheap; may be stale)."""
        try:
            if self.device is not None:
                return str(sd.query_devices(self.device)["name"])
            return str(sd.query_devices(kind="input")["name"])
        except Exception:
            return None

    def _open_stream_locked(self) -> None:
        """Open a fresh input stream bound to the current default device."""
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.CHUNK_FRAMES,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._active_device_name = self._resolve_input_name()
        self._warned_no_device = False
        logger.info(
            "Audio stream started ({}Hz, device={!r})",
            self.sample_rate,
            self._active_device_name or self.device,
        )

    def _close_stream_locked(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing audio stream: {}", exc)
            self._stream = None

    def _start_monitor(self) -> None:
        if self._monitor_thread is not None:
            return
        self._monitor_stop.clear()
        self._last_resync = time.monotonic()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="audio-device-monitor"
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self.MONITOR_INTERVAL_S):
            try:
                self._check_device()
            except Exception as exc:  # noqa: BLE001 — never let the watchdog die
                logger.debug("Device watchdog error: {}", exc)

    def _check_device(self) -> None:
        """Rebuild the stream if it died or the default input device changed."""
        # Never disrupt an in-progress recording.
        with self._lock:
            if self._recording:
                return

        stream = self._stream
        dead = stream is None or not stream.active

        # A cheap (possibly stale) read catches most default switches without the
        # cost of re-initialising PortAudio; the safety timer covers the rest.
        cheap_name = self._resolve_input_name()
        changed = (
            self.device is None
            and cheap_name is not None
            and cheap_name != self._active_device_name
        )
        due_resync = (time.monotonic() - self._last_resync) >= self.SAFETY_RESYNC_S

        if not (dead or changed or due_resync):
            return

        self._resync_default(reason="stream stopped" if dead else "device check")

    def _resync_default(self, reason: str) -> None:
        """Re-read PortAudio's device list and rebind to the current default.

        PortAudio caches the device list at init, so a full terminate/initialise
        is the only reliable way to pick up hot-plugged devices and default-device
        changes on Windows.
        """
        with self._rebuild_lock:
            self._last_resync = time.monotonic()
            previous = self._active_device_name
            self._close_stream_locked()
            try:
                sd._terminate()
                sd._initialize()
            except Exception as exc:  # noqa: BLE001
                logger.debug("PortAudio re-init failed: {}", exc)
            try:
                self._open_stream_locked()
            except Exception as exc:  # noqa: BLE001
                self._stream = None
                if not self._warned_no_device:
                    logger.warning("No usable input device ({}): {}", reason, exc)
                    self._warned_no_device = True
                return
            if self._active_device_name != previous:
                logger.info(
                    "Input device switched: {!r} → {!r} ({})",
                    previous,
                    self._active_device_name,
                    reason,
                )

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
