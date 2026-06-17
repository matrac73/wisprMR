"""
M1 test tool: records 5 seconds of audio and saves to test_output.wav.
Run: python tools/test_audio_capture.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from audio.capture import AudioCapture
import numpy as np
import wave


def main() -> None:
    logger.info("Starting audio capture test — recording 5 seconds...")
    cap = AudioCapture(sample_rate=16000, preroll_ms=500)
    cap.start_stream()
    time.sleep(0.3)  # let stream settle

    cap.begin_recording()
    logger.info("Recording... speak now!")
    time.sleep(5)
    audio = cap.end_recording()
    cap.stop_stream()

    out_path = "test_output.wav"
    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(out_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm.tobytes())

    duration = len(audio) / 16000
    logger.info("Saved {:.2f}s of audio to {}", duration, out_path)
    logger.info("Test passed: check {} in any audio player.", out_path)


if __name__ == "__main__":
    main()
