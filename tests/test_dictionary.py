"""Unit tests for vocab.dictionary."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from vocab.dictionary import VocabDictionary


def _make_dict(subs: dict) -> VocabDictionary:
    content = "substitutions:\n" + "".join(f'  "{k}": "{v}"\n' for k, v in subs.items())
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    d = VocabDictionary(path)
    return d


def test_basic_substitution():
    d = _make_dict({"adagia": "Adagia"})
    assert d.apply("hello adagia world") == "hello Adagia world"


def test_case_insensitive_match():
    d = _make_dict({"kpi": "KPI"})
    assert d.apply("the KPI and the kpi and the Kpi") == "the KPI and the KPI and the KPI"


def test_word_boundary():
    d = _make_dict({"ai": "AI"})
    result = d.apply("ai is amazing, email is not ai")
    # "email" should NOT be changed; "ai" at word boundaries should be
    assert "email" in result
    assert result.startswith("AI")


def test_empty_dict():
    d = _make_dict({})
    assert d.apply("hello world") == "hello world"


def test_no_file():
    d = VocabDictionary("nonexistent_file_xyz.yaml")
    assert d.apply("hello") == "hello"


def test_multiple_substitutions():
    d = _make_dict({"wispr": "Wispr", "adagia": "Adagia"})
    result = d.apply("wispr and adagia")
    assert result == "Wispr and Adagia"
