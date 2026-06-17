"""LLM post-processing via Ollama to clean transcribed text."""

from __future__ import annotations

import time
from typing import Optional

import httpx
from loguru import logger

SYSTEM_PROMPT_TEMPLATE = """Tu es un assistant de correction de texte dicté. Ton travail est de nettoyer le texte brut issu d'une reconnaissance vocale.

Règles strictes :
- Supprimer les hésitations et mots de remplissage : "euh", "um", "bah", "eh bien", "tu vois", "voilà", "genre", "en fait" (sauf si porteurs de sens).
- Corriger la ponctuation et la casse, ainsi que les accords grammaticaux évidents.
- Appliquer les corrections orales : si l'utilisateur dit "non en fait" ou "pardon je voulais dire", tenir compte de la correction.
- Conserver la langue d'origine du texte (ne pas traduire).
- Ne pas changer le sens ni le style de l'auteur.
- Interprêter les abréviations et les mots tronqués de manière cohérente avec le contexte.
- Interprêter les retours à la ligne et les pauses comme des séparateurs de phrases.
- Appliquer les substitutions du dictionnaire personnel suivant (si présentes) :{dict_section}
- Sortir UNIQUEMENT le texte corrigé, sans préambule, sans guillemets, sans commentaire ni explication.
"""


def _build_dict_section(substitutions: dict[str, str]) -> str:
    if not substitutions:
        return " (aucune)"
    lines = [f'\n  - "{k}" → "{v}"' for k, v in substitutions.items()]
    return "".join(lines)


class Polisher:
    """
    Polishes raw Whisper transcription via a local Ollama model.

    Falls back to raw text on timeout, connection error, or short input.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b-instruct-q4_K_M",
        fallback_model: Optional[str] = "qwen2.5:1.5b-instruct-q4_K_M",
        timeout_s: float = 8.0,
        min_chars: int = 15,
        keep_alive: int = -1,
        num_predict: int = 512,
        temperature: float = 0.2,
        substitutions: Optional[dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback_model = fallback_model
        self.timeout_s = timeout_s
        self.min_chars = min_chars
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.temperature = temperature
        self.enabled = True
        self.substitutions = substitutions or {}
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            dict_section=_build_dict_section(self.substitutions)
        )

    # ------------------------------------------------------------------
    # Réglages à chaud (panneau de l'overlay)
    # ------------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        logger.info("LLM polish {}.", "enabled" if enabled else "disabled")

    def set_model(self, model: str) -> None:
        if model and model != self.model:
            self.model = model
            logger.info("LLM polish model set to: {}", model)
            self.warmup()

    def ping(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception as exc:
            logger.warning("Ollama ping failed: {}", exc)
            return False

    def warmup(self) -> None:
        """Pre-load the model into Ollama RAM (uses a longer timeout than normal polish)."""
        logger.info("Warming up Ollama model '{}'...", self.model)
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "."}],
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": {"num_predict": 1, "temperature": 0.0},
            }
            with httpx.Client(timeout=120.0) as client:  # 2 min pour le cold start
                r = client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
            logger.info("Ollama warmup done.")
        except Exception as exc:
            logger.warning("Ollama warmup failed (non-fatal): {}", exc)

    def _call_ollama(self, text: str, model: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": self.num_predict,
                "temperature": self.temperature,
                # Réglages orientés latence : contexte court (dictée = phrases
                # brèves) et échantillonnage resserré → génération plus rapide.
                "num_ctx": 2048,
                "top_k": 20,
                "top_p": 0.9,
            },
        }
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
        data = r.json()
        return data["message"]["content"].strip()

    def polish(self, raw_text: str, context_hint: str = "") -> str:
        """
        Polish raw transcription text.

        Args:
            raw_text: Output from Whisper.
            context_hint: Active window process name (for logging/future use).

        Returns:
            Polished text, or raw_text on failure/short input.
        """
        if not self.enabled:
            return raw_text
        if len(raw_text) < self.min_chars:
            logger.debug(
                "Text too short ({} chars), skipping LLM polish.", len(raw_text)
            )
            return raw_text

        t0 = time.perf_counter()
        try:
            polished = self._call_ollama(raw_text, self.model)
            latency_s = time.perf_counter() - t0
            logger.info(
                "LLM | model={} | latency={:.2f}s | raw={!r} | polished={!r}",
                self.model,
                latency_s,
                raw_text[:60],
                polished[:60],
            )
            return polished
        except httpx.TimeoutException:
            logger.warning(
                "Ollama timeout after {:.1f}s — using raw Whisper text.", self.timeout_s
            )
        except httpx.ConnectError:
            logger.warning("Ollama not reachable — using raw Whisper text.")
        except Exception as exc:
            logger.warning("Ollama error: {} — using raw Whisper text.", exc)

        return raw_text
