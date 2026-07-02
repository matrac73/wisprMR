"""Mobile companion web server for Wispr MR.

Run this on the desktop/laptop that has Wispr MR installed, then open the shown
URL from an iPhone/Android on the same network. The phone records or uploads
audio; this server transcribes/polishes it locally and returns copyable text.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import av
import numpy as np
from av.audio.resampler import AudioResampler
from loguru import logger

from config_loader import load_config
from llm.polisher import Polisher
from stt.transcriber import Transcriber
from vocab.dictionary import VocabDictionary


PAGE = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wispr MR Mobile</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #101216; color: #f4f6fb; }
    main { max-width: 760px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 28px; margin: 0 0 18px; }
    button, input::file-selector-button { border: 0; border-radius: 8px; padding: 12px 16px; font-weight: 650; }
    button { background: #6ee7b7; color: #062014; margin: 6px 6px 6px 0; }
    button.secondary { background: #29303d; color: #f4f6fb; }
    textarea { width: 100%; min-height: 220px; box-sizing: border-box; border: 1px solid #333b49; border-radius: 8px; padding: 12px; background: #171b22; color: #f4f6fb; font-size: 16px; }
    .row { margin: 16px 0; }
    .muted { color: #aab3c2; font-size: 14px; }
    .status { min-height: 24px; color: #6ee7b7; }
  </style>
</head>
<body>
<main>
  <h1>Wispr MR Mobile</h1>
  <div class="row">
    <button id="record">Enregistrer</button>
    <button id="stop" class="secondary" disabled>Stop</button>
    <button id="copy" class="secondary">Copier</button>
  </div>
  <div class="row">
    <input id="file" type="file" accept="audio/*" capture>
  </div>
  <p id="status" class="status"></p>
  <textarea id="text" placeholder="La transcription apparait ici..."></textarea>
  <p class="muted">Si le bouton Enregistrer est refuse par le navigateur, utilise le champ fichier/audio. Sur mobile, certains navigateurs exigent HTTPS pour l'enregistrement direct.</p>
</main>
<script>
const statusEl = document.getElementById("status");
const textEl = document.getElementById("text");
const recordBtn = document.getElementById("record");
const stopBtn = document.getElementById("stop");
const fileInput = document.getElementById("file");
let recorder, chunks = [];

async function sendBlob(blob, name) {
  statusEl.textContent = "Transcription...";
  const response = await fetch("/api/transcribe", {
    method: "POST",
    headers: {"Content-Type": blob.type || "application/octet-stream"},
    body: blob
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Erreur serveur");
  textEl.value = data.text || "";
  statusEl.textContent = "Pret";
}

recordBtn.onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach(track => track.stop());
      sendBlob(new Blob(chunks, {type: recorder.mimeType || "audio/webm"}), "recording.webm").catch(err => statusEl.textContent = err.message);
    };
    recorder.start();
    recordBtn.disabled = true;
    stopBtn.disabled = false;
    statusEl.textContent = "Enregistrement...";
  } catch (err) {
    statusEl.textContent = "Micro direct indisponible. Utilise le champ fichier/audio.";
  }
};

stopBtn.onclick = () => {
  stopBtn.disabled = true;
  recordBtn.disabled = false;
  if (recorder && recorder.state !== "inactive") recorder.stop();
};

fileInput.onchange = async () => {
  if (fileInput.files.length) {
    sendBlob(fileInput.files[0], fileInput.files[0].name).catch(err => statusEl.textContent = err.message);
  }
};

document.getElementById("copy").onclick = async () => {
  await navigator.clipboard.writeText(textEl.value);
  statusEl.textContent = "Copie";
};
</script>
</body>
</html>
"""


def decode_audio(blob: bytes) -> np.ndarray:
    """Decode phone/browser audio to mono float32 PCM at 16 kHz."""
    resampler = AudioResampler(format="flt", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []
    with av.open(io.BytesIO(blob)) as container:
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                arr = resampled.to_ndarray()
                chunks.append(arr.reshape(-1).astype(np.float32))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(chunks).astype(np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1e-6:
        audio = audio / peak
    return audio


class MobileEngine:
    def __init__(self, profile: Optional[str]) -> None:
        self.cfg = load_config(profile=profile)
        self.dictionary = VocabDictionary()
        self.transcriber = Transcriber(
            model=self.cfg.stt.model,
            compute_type=self.cfg.stt.compute_type,
            cpu_threads=self.cfg.stt.cpu_threads,
            language=self.cfg.stt.language,
            beam_size=self.cfg.stt.beam_size,
            best_of=self.cfg.stt.best_of,
        )
        self.transcriber.warmup()
        self.polisher = None
        if self.cfg.llm.enabled:
            self.polisher = Polisher(
                base_url=self.cfg.llm.base_url,
                model=self.cfg.llm.model,
                fallback_model=self.cfg.llm.fallback_model,
                timeout_s=self.cfg.llm.timeout_s,
                min_chars=self.cfg.llm.min_chars_for_polish,
                keep_alive=self.cfg.llm.keep_alive,
                num_predict=self.cfg.llm.num_predict,
                temperature=self.cfg.llm.temperature,
                substitutions=self.dictionary.substitutions,
            )
            if not self.polisher.ping():
                self.polisher = None
        self.lock = threading.Lock()

    def transcribe(self, blob: bytes) -> str:
        audio = decode_audio(blob)
        if audio.size < 1600:
            return ""
        with self.lock:
            text = self.transcriber.transcribe(audio).text
            text = self.dictionary.apply(text)
            if self.polisher is not None:
                polished = self.polisher.polish(text, context_hint="mobile browser")
                if polished:
                    text = self.dictionary.apply(polished)
            return text


def make_handler(engine: MobileEngine):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path not in ("/api/transcribe", "/api/upload"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    raise ValueError("audio vide")
                blob = self.rfile.read(length)
                text = engine.transcribe(blob)
                payload = json.dumps({"text": text}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                logger.exception("Mobile transcription failed: {}", exc)
                payload = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, fmt: str, *args) -> None:
            logger.debug(fmt, *args)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Wispr MR mobile companion server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--profile", choices=["fast", "balanced", "quality"], default=None)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="INFO")

    engine = MobileEngine(profile=args.profile)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(engine))
    logger.info("Mobile server ready: http://{}:{}/", args.host, args.port)
    logger.info("From phone: open http://<computer-ip>:{} on the same Wi-Fi.", args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
