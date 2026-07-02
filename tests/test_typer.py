"""Unit tests for inject.typer (clipboard mocked)."""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from inject.typer import TextInjector


def test_inject_calls_clipboard_and_paste():
    injector = TextInjector(method="clipboard", paste_delay_ms=0)
    with patch("inject.typer.pyperclip.paste", return_value="old"),          patch("inject.typer.pyperclip.copy") as mock_copy,          patch("inject.typer.keyboard.send") as mock_send:
        injector.inject("Hello world")
    mock_copy.assert_any_call("Hello world")
    mock_send.assert_called_with("ctrl+v")
    # Restore old clipboard
    mock_copy.assert_called_with("old")


def test_inject_restores_clipboard_on_error():
    injector = TextInjector(method="clipboard", paste_delay_ms=0)
    with patch("inject.typer.pyperclip.paste", return_value="saved"),          patch("inject.typer.pyperclip.copy") as mock_copy,          patch("inject.typer.keyboard.send", side_effect=RuntimeError("err")):
        try:
            injector.inject("text")
        except RuntimeError:
            pass
    # Restore should still happen (finally block)
    mock_copy.assert_called_with("saved")


def test_inject_empty_does_nothing():
    injector = TextInjector(method="clipboard", paste_delay_ms=0)
    with patch("inject.typer.pyperclip.paste") as mock_paste:
        injector.inject("")
    mock_paste.assert_not_called()


def test_two_pass_replace():
    injector = TextInjector(method="clipboard", paste_delay_ms=0)
    with patch("inject.typer.pyperclip.paste", return_value=""),          patch("inject.typer.pyperclip.copy"),          patch("inject.typer.keyboard.send"),          patch("inject.typer.keyboard.send") as mock_send:
        injector.inject_raw("raw text")  # len = 8
        injector.replace_with_polished("polished")
    # Should have sent backspace 8 times
    backspace_calls = [c for c in mock_send.call_args_list if c == call("backspace")]
    assert len(backspace_calls) == 8
