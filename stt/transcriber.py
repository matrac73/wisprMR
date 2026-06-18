"""Whisper STT via faster-whisper (CPU, int8)."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
from faster_whisper import WhisperModel
from loguru import logger

# ---------------------------------------------------------------------------
# Résolution du modèle
# ---------------------------------------------------------------------------
# large-v3-turbo (décodeur 4 couches) est ~6-8x plus rapide que large-v3 sur
# CPU pour une précision quasi-identique → c'est LE bon défaut. faster-whisper
# < 1.1.0 ne connaît pas l'alias, on pointe donc directement le dépôt CT2.
_TURBO_ALIASES = {"large-v3-turbo", "turbo", "large-v3-turbo-ct2", "deepdml"}
_TURBO_REPO = "deepdml/faster-whisper-large-v3-turbo-ct2"

# Chaîne de repli si le modèle demandé ne se charge pas (réseau coupé, etc.).
_FALLBACK_CHAIN = ["medium", "small", "base"]


def _resolve_model_name(name: str) -> str:
    """Mappe les alias turbo vers un identifiant chargeable quelle que soit
    la version de faster-whisper."""
    if name.strip().lower() in _TURBO_ALIASES:
        return _TURBO_REPO
    return name


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration_s: float
    latency_s: float


class Transcriber:
    """
    Loads a faster-whisper model once and exposes a transcribe() method.

    CPU-optimised defaults: int8, beam_size configurable, vad_filter=True.
    Supports an `initial_prompt` to bias recognition toward domain vocabulary,
    and live reloading of the model / language for the settings panel.
    """

    def __init__(
        self,
        model: str = "large-v3-turbo",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        language: Optional[str] = None,
        beam_size: int = 1,
        best_of: int = 1,
        initial_prompt: Optional[str] = None,
    ) -> None:
        self.requested_model = model
        self.model_name = model
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.best_of = best_of
        self.initial_prompt = initial_prompt

        self._threads = cpu_threads if cpu_threads > 0 else os.cpu_count() or 4
        self._lock = threading.Lock()  # protège _model pendant un reload à chaud
        self._model = self._load_model(model)

    # ------------------------------------------------------------------
    # Chargement (avec chaîne de repli)
    # ------------------------------------------------------------------

    def _load_model(self, model: str) -> WhisperModel:
        candidates = [_resolve_model_name(model)]
        for fb in _FALLBACK_CHAIN:
            if fb not in candidates:
                candidates.append(fb)

        last_exc: Optional[Exception] = None
        for candidate in candidates:
            try:
                logger.info(
                    "Loading Whisper model '{}' (threads={}, compute_type={})",
                    candidate,
                    self._threads,
                    self.compute_type,
                )
                m = WhisperModel(
                    candidate,
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=self._threads,
                    num_workers=1,
                )
                self.model_name = candidate
                logger.info("Whisper model '{}' loaded.", candidate)
                return m
            except Exception as exc:  # noqa: BLE001 — on tente le repli suivant
                last_exc = exc
                logger.warning("Failed to load Whisper model '{}': {}", candidate, exc)

        raise RuntimeError(f"Could not load any Whisper model: {last_exc}")

    def reload_model(
        self,
        model: str,
        beam_size: Optional[int] = None,
        best_of: Optional[int] = None,
    ) -> None:
        """Recharge un nouveau modèle à chaud (pour le changement de profil
        depuis le panneau de réglages). Thread-safe."""
        if beam_size is not None:
            self.beam_size = beam_size
        if best_of is not None:
            self.best_of = best_of
        if _resolve_model_name(model) == self.model_name and model == self.requested_model:
            logger.debug("reload_model: '{}' déjà chargé, no-op.", model)
            return
        logger.info("Reloading Whisper model → '{}'", model)
        new_model = self._load_model(model)
        with self._lock:
            self.requested_model = model
            self._model = new_model
        self.warmup()

    # ------------------------------------------------------------------
    # Réglages à chaud
    # ------------------------------------------------------------------

    def set_language(self, language: Optional[str]) -> None:
        """None = auto-détection."""
        self.language = language or None
        logger.info("STT language set to: {}", self.language or "auto")

    def set_initial_prompt(self, prompt: Optional[str]) -> None:
        self.initial_prompt = prompt or None

    # ------------------------------------------------------------------
    # Inférence
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Run one silent inference to JIT-compile kernels before first real use."""
        # vad_filter=False : le VAD sur du silence retourne 0 segments → max() plante
        silent = np.zeros(16000, dtype=np.float32)  # 1 s silence
        with self._lock:
            segments, _ = self._model.transcribe(
                silent, beam_size=1, best_of=1, vad_filter=False
            )
            list(segments)  # consommer le générateur pour déclencher l'inférence
        logger.info("Whisper warmup done.")

    def transcribe_segment(self, audio: np.ndarray) -> str:
        """Fast, greedy transcription of one streamed segment.

        Used by the streaming session for chunks committed during recording and
        for the final tail. Always beam_size=1 (greedy = lowest latency), VAD on
        to drop any silence we included, and the segment is peak-normalised to
        match the amplitude the offline path feeds the model.
        """
        if audio is None or len(audio) == 0:
            return ""
        peak = float(np.max(np.abs(audio)))
        if peak > 1e-6:
            audio = (audio / peak).astype(np.float32)
        with self._lock:
            try:
                segments, _ = self._model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=1,
                    best_of=1,
                    condition_on_previous_text=False,
                    initial_prompt=self.initial_prompt,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 300},
                    word_timestamps=False,
                )
                return " ".join(seg.text.strip() for seg in segments).strip()
            except ValueError:
                # VAD filtered everything (silence) → empty segment.
                return ""
            except Exception as exc:  # noqa: BLE001
                logger.debug("transcribe_segment error: {}", exc)
                return ""

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> TranscriptionResult:
        """
        Transcribe audio array.

        Args:
            audio: float32 mono PCM.
            sample_rate: must be 16000.

        Returns:
            TranscriptionResult with text, language, duration and latency.
        """
        if sample_rate != 16000:
            raise ValueError(f"Whisper requires 16000Hz, got {sample_rate}")

        duration_s = len(audio) / sample_rate
        t0 = time.perf_counter()

        with self._lock:
            try:
                segments, info = self._model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=self.beam_size,
                    best_of=self.best_of,
                    condition_on_previous_text=False,
                    initial_prompt=self.initial_prompt,
                    vad_filter=True,
                    # Coupe les silences sans tronquer les fins de mots.
                    vad_parameters={"min_silence_duration_ms": 300},
                    word_timestamps=False,
                )
                text = " ".join(seg.text.strip() for seg in segments).strip()
                lang = info.language
            except ValueError:
                # VAD a tout filtré (silence / clip trop court) → en mode
                # langue auto, faster-whisper plante sur max() vide. On
                # retourne simplement une transcription vide.
                logger.debug("Aucune parole détectée (VAD vide).")
                text = ""
                lang = self.language or ""
        latency_s = time.perf_counter() - t0

        logger.info(
            "STT | model={} | lang={} | dur={:.2f}s | latency={:.2f}s | text={!r}",
            self.model_name,
            lang,
            duration_s,
            latency_s,
            text[:80],
        )
        return TranscriptionResult(
            text=text,
            language=lang,
            duration_s=duration_s,
            latency_s=latency_s,
        )
