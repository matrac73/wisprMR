"""Typed config loading with Pydantic from config.yaml + profile presets."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Profils de vitesse — surcharge les sections stt/llm de la config de base
# ---------------------------------------------------------------------------

# NB : tous les profils utilisent large-v3-turbo (décodeur 4 couches → très
# rapide sur CPU ET plus précis que small/medium). Les profils ne touchent PAS
# à `llm.enabled` : l'activation du polish est un réglage indépendant piloté
# par le toggle du panneau overlay (clé top-level `llm.enabled`).
# NB : sur ce CPU portable (i7-1355U, sans GPU), large-v3-turbo tourne à ~2x
# PLUS LENT que le temps réel → incompatible avec l'objectif ≤1s. Les profils
# rapides utilisent donc des modèles plus légers (small/base) + la transcription
# en streaming (la majeure partie du travail est faite PENDANT que l'on parle).
# 'quality' garde turbo pour la précision maximale, au prix de la latence.
PROFILES: dict[str, dict] = {
    "fast": {
        # base (~0.7s pour 5s d'audio) + streaming → insertion quasi-instantanée.
        "stt": {"model": "base", "compute_type": "int8", "beam_size": 1, "best_of": 1, "streaming": True},
        "llm": {"model": "qwen2.5:1.5b-instruct-q4_K_M", "timeout_s": 4},
    },
    "balanced": {
        # small (~2s pour 5s) + streaming : bon compromis précision/latence, ≤1s perçu.
        "stt": {"model": "small", "compute_type": "int8", "beam_size": 1, "best_of": 1, "streaming": True},
        "llm": {"model": "qwen2.5:1.5b-instruct-q4_K_M", "timeout_s": 5},
    },
    "quality": {
        # large-v3-turbo : précision maximale. LENT sur ce CPU (~8s+) même avec
        # le streaming — à réserver aux cas où la latence importe peu.
        "stt": {"model": "large-v3-turbo", "compute_type": "int8", "beam_size": 5, "best_of": 5, "streaming": True},
        "llm": {"model": "qwen2.5:3b-instruct-q4_K_M", "timeout_s": 8},
    },
}


# ---------------------------------------------------------------------------
# Modèles Pydantic
# ---------------------------------------------------------------------------

class AudioConfig(BaseModel):
    sample_rate: int = 16000
    preroll_ms: int = 500
    max_record_s: float = 120.0
    device: Optional[int | str] = None


class SttConfig(BaseModel):
    model: str = "base"
    compute_type: str = "int8"
    cpu_threads: int = 0
    language: Optional[str] = None
    beam_size: int = 1
    best_of: int = 1
    streaming: bool = True       # transcribe progressively while recording


class LlmConfig(BaseModel):
    enabled: bool = True
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:3b-instruct-q4_K_M"
    fallback_model: Optional[str] = "qwen2.5:1.5b-instruct-q4_K_M"
    timeout_s: float = 8.0
    min_chars_for_polish: int = 15
    keep_alive: int = -1
    num_predict: int = 256
    temperature: float = 0.2


class InjectionConfig(BaseModel):
    method: str = "clipboard"
    two_pass_insertion: bool = False
    paste_delay_ms: int = 30


class UiConfig(BaseModel):
    overlay: bool = True
    tray: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/app.log"
    rotation: str = "10 MB"
    retention: str = "7 days"


class AppConfig(BaseModel):
    profile: Optional[str] = None
    hotkey: str = "ctrl+space"
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    injection: InjectionConfig = Field(default_factory=InjectionConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, overrides: dict) -> dict:
    """Merge overrides into base (one level deep for sub-sections)."""
    result = dict(base)
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **val}
        else:
            result[key] = val
    return result


def load_config(
    path: str | Path = "config.yaml",
    profile: Optional[str] = None,
) -> AppConfig:
    """
    Load AppConfig from YAML, then apply a speed profile if specified.

    Profile priority: CLI --profile arg > config.yaml `profile:` key > no profile.
    """
    p = Path(path)
    data: dict = {}
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    # Determine active profile
    active = profile or data.get("profile")
    if active and active in PROFILES:
        data = _deep_merge(data, PROFILES[active])
    elif active:
        import sys
        if sys.stderr is not None:
            print(f"[warn] Unknown profile '{active}'. Valid: {list(PROFILES)}", file=sys.stderr)

    return AppConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Écriture / persistance (utilisé par le panneau de réglages de l'overlay)
# ---------------------------------------------------------------------------

# Chemins supportés par le panneau de réglages, en notation pointée.
# Permet de mettre à jour config.yaml sans perdre les commentaires.
_WRITABLE_KEYS = {
    "profile",
    "hotkey",
    "stt.model",
    "stt.language",
    "stt.beam_size",
    "llm.enabled",
    "llm.model",
    "injection.two_pass_insertion",
}


def update_config_file(updates: dict, path: str | Path = "config.yaml") -> bool:
    """
    Met à jour des clés de config.yaml *sur disque* en notation pointée.

    Préserve commentaires et mise en forme via ruamel.yaml si disponible,
    sinon retombe sur PyYAML (commentaires perdus).

    Args:
        updates: ex. {"profile": "fast", "llm.enabled": False}.
        path: chemin du fichier config.

    Returns:
        True si l'écriture a réussi.
    """
    p = Path(path)
    safe_updates = {k: v for k, v in updates.items() if k in _WRITABLE_KEYS}
    if not safe_updates:
        return False

    try:
        from ruamel.yaml import YAML

        yaml_rt = YAML()
        yaml_rt.preserve_quotes = True
        with p.open(encoding="utf-8") as fh:
            data = yaml_rt.load(fh) or {}
        for dotted, value in safe_updates.items():
            _set_dotted(data, dotted, value)
        with p.open("w", encoding="utf-8") as fh:
            yaml_rt.dump(data, fh)
        return True
    except ImportError:
        # Fallback : PyYAML (perd les commentaires)
        data = {}
        if p.exists():
            with p.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        for dotted, value in safe_updates.items():
            _set_dotted(data, dotted, value)
        with p.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        return True
    except Exception:
        return False


def _set_dotted(data: dict, dotted: str, value) -> None:
    """Set data['a']['b'] = value for dotted='a.b', creating dicts as needed."""
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
