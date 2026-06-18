"""Benchmark Whisper STT latency at various CPU thread counts on this machine."""
import os
import time

import numpy as np
from faster_whisper import WhisperModel

REPO = "deepdml/faster-whisper-large-v3-turbo-ct2"

# A 5 s synthetic voiced-ish signal (formant-like sum of sines, amplitude-modulated)
sr = 16000
dur = 5.0
t = np.linspace(0, dur, int(sr * dur), endpoint=False)
sig = (
    0.3 * np.sin(2 * np.pi * 140 * t)
    + 0.2 * np.sin(2 * np.pi * 700 * t)
    + 0.1 * np.sin(2 * np.pi * 1800 * t)
)
sig *= 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)  # 4 Hz syllable-rate modulation
audio = (sig / np.max(np.abs(sig))).astype(np.float32)


def bench(threads, model="turbo", compute="int8", n=3):
    name = REPO if model == "turbo" else model
    m = WhisperModel(name, device="cpu", compute_type=compute, cpu_threads=threads, num_workers=1)
    # warmup
    list(m.transcribe(np.zeros(sr, dtype=np.float32), beam_size=1, vad_filter=False)[0])
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        segs, _ = m.transcribe(audio, language="fr", beam_size=1, best_of=1,
                               condition_on_previous_text=False, vad_filter=False)
        list(segs)
        times.append(time.perf_counter() - t0)
    print(f"  model={model:8} compute={compute:5} threads={threads:2} -> "
          f"min={min(times):.2f}s med={sorted(times)[len(times)//2]:.2f}s (audio={dur}s)")


if __name__ == "__main__":
    print(f"cpu_count={os.cpu_count()}")
    for th in (4, 6, 8, 12):
        bench(th, "turbo", "int8")
    # Smaller models for comparison
    for mdl in ("small", "base"):
        bench(6, mdl, "int8")
