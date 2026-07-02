"""Text injection into the active window via clipboard + Ctrl+V."""
from __future__ import annotations

import sys
import time
from typing import Optional

import pyperclip
from loguru import logger

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except ImportError:
    keyboard = None
    _KEYBOARD_AVAILABLE = False

try:
    from pynput.keyboard import Controller, Key
    _PYNPUT_AVAILABLE = True
except ImportError:
    Controller = None
    Key = None
    _PYNPUT_AVAILABLE = False


class TextInjector:
    """
    Injects text at the current cursor position using the clipboard.

    Method:
      1. Save the current clipboard contents.
      2. Copy the new text to the clipboard.
      3. Send Ctrl+V.
      4. Restore the old clipboard contents after a short delay.

    inject_raw() / replace_with_polished() (two-pass):
      First injects raw Whisper text immediately, then when polished text
      arrives, sends N backspaces and pastes the polished version.
      WARNING: Fragile if the cursor moves between the two passes.
    """

    def __init__(
        self,
        method: str = "clipboard",
        paste_delay_ms: int = 30,
    ) -> None:
        if method not in ("clipboard", "type"):
            raise ValueError(f"Unknown injection method: {method!r}")
        self.method = method
        self.paste_delay_s = paste_delay_ms / 1000.0
        self._last_raw_len: int = 0
        self._controller = Controller() if _PYNPUT_AVAILABLE else None

    def _save_clipboard(self) -> Optional[str]:
        try:
            return pyperclip.paste()
        except Exception:
            return None

    def _restore_clipboard(self, old: Optional[str]) -> None:
        if old is None:
            return
        try:
            pyperclip.copy(old)
        except Exception:
            pass

    def _paste_text(self, text: str) -> None:
        old = self._save_clipboard()
        try:
            pyperclip.copy(text)
            time.sleep(self.paste_delay_s)
            self._send_paste_shortcut()
            time.sleep(self.paste_delay_s)
        finally:
            self._restore_clipboard(old)

    def _send_paste_shortcut(self) -> None:
        if sys.platform == "win32" and _KEYBOARD_AVAILABLE:
            keyboard.send("ctrl+v")
            return
        if not self._controller or Key is None:
            raise RuntimeError("No keyboard controller available for paste shortcut.")
        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with self._controller.pressed(modifier):
            self._controller.press("v")
            self._controller.release("v")

    def _send_backspace(self) -> None:
        if sys.platform == "win32" and _KEYBOARD_AVAILABLE:
            keyboard.send("backspace")
            return
        if not self._controller or Key is None:
            raise RuntimeError("No keyboard controller available for backspace.")
        self._controller.press(Key.backspace)
        self._controller.release(Key.backspace)

    def _type_text(self, text: str) -> None:
        if sys.platform == "win32" and _KEYBOARD_AVAILABLE:
            keyboard.write(text, delay=0.01)
            return
        if not self._controller:
            raise RuntimeError("No keyboard controller available for typing.")
        self._controller.type(text)

    def inject(self, text: str) -> None:
        """Inject text at the current cursor position."""
        if not text:
            return
        logger.debug("Injecting {} chars via {}.", len(text), self.method)
        if self.method == "clipboard":
            self._paste_text(text)
        else:
            self._type_text(text)
        logger.info("Injected: {!r}", text[:80])

    def inject_raw(self, raw_text: str) -> None:
        """First pass: inject raw Whisper text immediately (two_pass mode)."""
        self._last_raw_len = len(raw_text)
        self.inject(raw_text)

    def replace_with_polished(self, polished_text: str) -> None:
        """
        Second pass: erase the previously injected raw text and paste polished.

        WARNING: If the cursor has moved since inject_raw(), this will corrupt text.
        """
        if self._last_raw_len > 0:
            for _ in range(self._last_raw_len):
                self._send_backspace()
                time.sleep(0.002)
        self.inject(polished_text)
        self._last_raw_len = 0
