"""Streaming transcription: transcribe audio *while* the user speaks.

The expensive part of dictation latency is running Whisper on the whole clip
*after* the mic is released. On a CPU-only laptop this dominates (several
seconds). This module removes most of it from the critical path: during
recording, a background worker transcribes the audio progressively, committing
chunks at natural silences. When the user releases the key, only the short
remaining *tail* (the audio since the last pause) still needs transcribing — so
the perceived latency drops from "whole utterance" to "last ~1 second".

Chunks are cut at detected silence boundaries to avoid splitting words; a
forced cut bounds the tail length when the user never pauses. Each committed
segment is passed to the Whisper VAD, so any silence we accidentally include is
filtered out (empty segments are simply dropped).
"""
from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

if TYPE_CHECKING:  # avoid import cycle at runtime
    from stt.transcriber import Transcriber


class StreamingSession:
    """Drives progressive transcription for a single push-to-talk recording.

    Lifecycle: ``start()`` → ``feed(chunk)`` (many times, from the audio
    thread) → ``finish()`` (returns the full transcript).
    """

    def __init__(
        self,
        transcriber: "Transcriber",
        sample_rate: int = 16000,
        commit_min_s: float = 0.9,
        force_commit_s: float = 2.2,
        silence_ms: int = 260,
        frame_ms: int = 30,
        poll_s: float = 0.12,
    ) -> None:
        self.tr = transcriber
        self.sr = sample_rate
        self.commit_min = int(commit_min_s * sample_rate)
        self.force_commit = int(force_commit_s * sample_rate)
        self.frame = int(frame_ms * sample_rate / 1000)
        self.sil_frames = max(1, round(silence_ms / frame_ms))
        self.poll_s = poll_s

        self._pending: deque[np.ndarray] = deque()  # uncommitted audio chunks
        self._pending_samples = 0
        self._committed: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="stt-stream"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._worker.start()

    def feed(self, chunk: np.ndarray) -> None:
        """Append live audio (called from the real-time audio callback — cheap)."""
        if chunk is None or len(chunk) == 0:
            return
        with self._lock:
            self._pending.append(chunk.astype(np.float32, copy=True))
            self._pending_samples += len(chunk)

    def finish(self) -> str:
        """Stop streaming, transcribe the remaining tail, return the full text."""
        self._stop.set()
        self._worker.join(timeout=30.0)
        # Flush everything that's left (the tail since the last commit).
        self._commit(final=True)
        with self._lock:
            return " ".join(t for t in self._committed if t).strip()

    def cancel(self) -> None:
        """Abort without transcribing the tail (e.g. clip too short)."""
        self._stop.set()
        self._worker.join(timeout=5.0)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._commit(final=False)
            except Exception as exc:  # noqa: BLE001 — never kill the worker
                logger.debug("streaming commit error: {}", exc)
            self._stop.wait(self.poll_s)

    def _commit(self, final: bool) -> None:
        """Transcribe and commit a prefix of the pending audio, if appropriate."""
        with self._lock:
            if not self._pending:
                return
            buf = np.concatenate(self._pending)

        if not final and len(buf) < self.commit_min:
            return

        cut = len(buf) if final else self._find_cut(buf)
        if cut is None or cut <= 0:
            return

        segment = buf[:cut]
        text = self.tr.transcribe_segment(segment)
        with self._lock:
            if text:
                self._committed.append(text)
            self._drop_front(cut)

    def _drop_front(self, n: int) -> None:
        """Remove the first ``n`` samples from the pending deque (lock held)."""
        remaining = n
        while remaining > 0 and self._pending:
            head = self._pending[0]
            if len(head) <= remaining:
                remaining -= len(head)
                self._pending.popleft()
                self._pending_samples -= len(head)
            else:
                self._pending[0] = head[remaining:]
                self._pending_samples -= remaining
                remaining = 0

    def _find_cut(self, buf: np.ndarray) -> int | None:
        """Pick a sample index to commit up to.

        Prefers the latest silence gap that still leaves >= ``commit_min`` of
        committed audio (so words aren't split). If the speaker never pauses,
        forces a least-bad cut once the pending audio exceeds ``force_commit``
        to keep the release-time tail short.
        """
        nframes = len(buf) // self.frame
        if nframes < 2:
            return None

        frames = buf[: nframes * self.frame].reshape(nframes, self.frame)
        rms = np.sqrt(np.mean(frames * frames, axis=1))
        peak = float(rms.max())
        if peak <= 1e-7:
            # Pure silence: only flush it once it grows, so VAD can drop it.
            return len(buf) if len(buf) >= self.force_commit else None

        thr = peak * 0.18
        silent = rms < thr
        min_frame = self.commit_min // self.frame

        # Latest qualifying silence run → cut at its middle.
        best_cut: int | None = None
        i = nframes - 1
        while i >= min_frame:
            if silent[i]:
                end = i
                start = i
                while start - 1 >= 0 and silent[start - 1]:
                    start -= 1
                if end - start + 1 >= self.sil_frames and start >= min_frame:
                    best_cut = ((start + end) // 2) * self.frame
                    break
                i = start - 1
            else:
                i -= 1

        if best_cut is not None:
            return best_cut

        # No usable pause yet — force a cut at the quietest frame if too long.
        if len(buf) >= self.force_commit:
            window = rms[min_frame : nframes - 1]
            if len(window) > 0:
                quietest = min_frame + int(np.argmin(window))
                return quietest * self.frame
        return None
