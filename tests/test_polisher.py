"""Unit tests for llm.polisher short-circuit and fallback logic."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llm.polisher import Polisher


def _make_polisher(**kwargs) -> Polisher:
    defaults = dict(
        base_url="http://localhost:11434",
        model="qwen2.5:3b-instruct-q4_K_M",
        timeout_s=5.0,
        min_chars=15,
    )
    defaults.update(kwargs)
    return Polisher(**defaults)


def test_short_text_skips_llm():
    p = _make_polisher(min_chars=15)
    short = "Bonjour"
    with patch.object(p, "_call_ollama") as mock_call:
        result = p.polish(short)
    mock_call.assert_not_called()
    assert result == short


def test_timeout_fallback():
    import httpx
    p = _make_polisher(min_chars=5, timeout_s=0.001)
    with patch.object(p, "_call_ollama", side_effect=httpx.TimeoutException("timeout")):
        result = p.polish("euh donc voilà le truc")
    assert result == "euh donc voilà le truc"


def test_connect_error_fallback():
    import httpx
    p = _make_polisher(min_chars=5)
    with patch.object(p, "_call_ollama", side_effect=httpx.ConnectError("refused")):
        result = p.polish("euh donc voilà le truc")
    assert result == "euh donc voilà le truc"


def test_successful_polish():
    p = _make_polisher(min_chars=5)
    with patch.object(p, "_call_ollama", return_value="Voilà le truc."):
        result = p.polish("euh donc voilà le truc")
    assert result == "Voilà le truc."


def test_empty_text_not_sent():
    p = _make_polisher(min_chars=1)
    with patch.object(p, "_call_ollama") as mock_call:
        result = p.polish("")
    mock_call.assert_not_called()
    assert result == ""
