"""
M2 test tool: transcribes a WAV file using faster-whisper.
Run: python tools/test_transcribe.py path/to/audio.wav
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from config_loader import load_config
from stt.transcriber import Transcriber


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "r") as wf:
        if wf.getframerate() != 16000:
            raise ValueError(f"WAV must be 16000Hz, got {wf.getframerate()}Hz")
        raw = wf.readframes(wf.getnframes())
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/test_transcribe.py <audio.wav>")
        sys.exit(1)

    wav_path = sys.argv[1]
    cfg = load_config()
    s = cfg.stt

    logger.info("Loading Whisper model '{}'...", s.model)
    transcriber = Transcriber(
        model=s.model,
        compute_type=s.compute_type,
        cpu_threads=s.cpu_threads,
        language=s.language,
        beam_size=s.beam_size,
        best_of=s.best_of,
    )
    transcriber.warmup()

    audio = load_wav(wav_path)
    logger.info("Transcribing {:.2f}s of audio...", len(audio) / 16000)
    result = transcriber.transcribe(audio)

    print()
    print(f"Language : {result.language}")
    print(f"Duration : {result.duration_s:.2f}s")
    print(f"Latency  : {result.latency_s:.2f}s")
    print(f"Text     : {result.text}")


if __name__ == "__main__":
    main()
