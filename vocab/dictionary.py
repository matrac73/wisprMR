"""Personal vocabulary dictionary: load and apply word substitutions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger


class VocabDictionary:
    """
    Loads substitution pairs from dictionary.yaml and applies them to text.

    Matching is case-insensitive; replacement preserves the case of the
    corrected form exactly as written in the YAML file.
    """

    def __init__(self, path: str | Path = "dictionary.yaml") -> None:
        self._path = Path(path)
        self.substitutions: dict[str, str] = {}
        self._patterns: list[tuple[re.Pattern[str], str]] = []
        self.load()

    def load(self) -> None:
        """(Re-)load dictionary from disk."""
        if not self._path.exists():
            logger.debug("dictionary.yaml not found — substitutions disabled.")
            return
        try:
            with self._path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            subs: dict = data.get("substitutions") or {}
            self.substitutions = {str(k): str(v) for k, v in subs.items()}
            self._compile()
            logger.info("Dictionary loaded: {} substitution(s).", len(self.substitutions))
        except Exception as exc:
            logger.warning("Failed to load dictionary.yaml: {}", exc)

    def _compile(self) -> None:
        self._patterns = [
            (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.IGNORECASE), v)
            for k, v in self.substitutions.items()
        ]

    def apply(self, text: str) -> str:
        """Apply all substitutions to text and return the result."""
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text
