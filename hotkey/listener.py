"""Push-to-talk hotkey listener (hold = record, release = stop)."""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional

from loguru import logger

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except ImportError:
    keyboard = None
    _KEYBOARD_AVAILABLE = False

try:
    from pynput import keyboard as pynput_keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    pynput_keyboard = None
    _PYNPUT_AVAILABLE = False


class HotkeyListener:
    """
    Listens for a configurable hold-hotkey (default: ctrl+space).

    Windows uses the `keyboard` package when available. macOS/Linux use
    `pynput`, which requires Accessibility/Input Monitoring permission on macOS.
    """

    def __init__(
        self,
        hotkey: str = "ctrl+space",
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        min_hold_ms: int = 300,
    ) -> None:
        self.hotkey = hotkey
        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel
        self.min_hold_ms = min_hold_ms

        self._pressed = False
        self._press_time: float = 0.0
        self._enabled = True
        self._thread: Optional[threading.Thread] = None
        self._pynput_listener = None

    def _handle_press(self) -> None:
        if not self._enabled or self._pressed:
            return
        self._pressed = True
        self._press_time = time.monotonic()
        logger.debug("Hotkey pressed.")
        if self.on_press:
            try:
                self.on_press()
            except Exception as exc:
                logger.exception("on_press callback error: {}", exc)

    def _handle_release(self) -> None:
        if not self._pressed:
            return
        held_ms = (time.monotonic() - self._press_time) * 1000
        self._pressed = False
        if held_ms < self.min_hold_ms:
            logger.debug("Hotkey held only {:.0f}ms - ignoring.", held_ms)
            if self.on_cancel:
                try:
                    self.on_cancel()
                except Exception as exc:
                    logger.exception("on_cancel callback error: {}", exc)
            return
        logger.debug("Hotkey released after {:.0f}ms.", held_ms)
        if self.on_release:
            try:
                self.on_release()
            except Exception as exc:
                logger.exception("on_release callback error: {}", exc)

    def _parse_hotkey(self) -> tuple[set[str], str]:
        parts = [p.strip().lower() for p in self.hotkey.split("+")]
        return set(parts[:-1]), parts[-1]

    def start(self) -> None:
        """Start listening in a background thread."""
        if sys.platform == "win32" and _KEYBOARD_AVAILABLE:
            self._start_keyboard_listener()
        elif _PYNPUT_AVAILABLE:
            self._start_pynput_listener()
        else:
            logger.error("No supported keyboard listener available - hotkey disabled.")

    def _start_keyboard_listener(self) -> None:
        modifiers, trigger = self._parse_hotkey()
        mod_aliases: dict[str, set[str]] = {
            "ctrl": {"ctrl", "left ctrl", "right ctrl"},
            "control": {"ctrl", "left ctrl", "right ctrl"},
            "shift": {"shift", "left shift", "right shift"},
            "alt": {"alt", "left alt", "right alt"},
            "option": {"alt", "left alt", "right alt"},
            "cmd": {"windows", "left windows", "right windows"},
            "command": {"windows", "left windows", "right windows"},
            "win": {"windows", "left windows", "right windows"},
        }
        mod_names = {alias for m in modifiers for alias in mod_aliases.get(m, {m})}
        held_mods: set[str] = set()

        def modifiers_ready() -> bool:
            if not modifiers:
                return True
            for modifier in modifiers:
                aliases = mod_aliases.get(modifier, {modifier})
                if not any(alias in held_mods for alias in aliases):
                    return False
            return True

        def on_event(event: "keyboard.KeyboardEvent") -> None:
            name = event.name.lower() if event.name else ""
            if name in mod_names:
                if event.event_type == keyboard.KEY_DOWN:
                    held_mods.add(name)
                else:
                    held_mods.discard(name)
                    if self._pressed:
                        self._handle_release()
                return

            if name == trigger:
                if event.event_type == keyboard.KEY_DOWN and modifiers_ready():
                    self._handle_press()
                elif event.event_type == keyboard.KEY_UP and self._pressed:
                    self._handle_release()

        def listen() -> None:
            keyboard.hook(on_event)
            logger.info("Hotkey listener active: hold '{}' to record.", self.hotkey)
            keyboard.wait()

        self._thread = threading.Thread(target=listen, daemon=True, name="hotkey-listener")
        self._thread.start()

    def _start_pynput_listener(self) -> None:
        modifiers, trigger = self._parse_hotkey()
        mod_aliases: dict[str, set[str]] = {
            "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
            "control": {"ctrl", "ctrl_l", "ctrl_r"},
            "shift": {"shift", "shift_l", "shift_r"},
            "alt": {"alt", "alt_l", "alt_r", "option"},
            "option": {"alt", "alt_l", "alt_r", "option"},
            "cmd": {"cmd", "cmd_l", "cmd_r", "command"},
            "command": {"cmd", "cmd_l", "cmd_r", "command"},
            "win": {"cmd", "cmd_l", "cmd_r", "command"},
        }
        held_mods: set[str] = set()

        def key_name(key) -> str:
            if hasattr(key, "char") and key.char:
                return str(key.char).lower()
            return str(getattr(key, "name", None) or key).replace("Key.", "").lower()

        def trigger_matches(name: str) -> bool:
            return name == trigger or (trigger == "space" and name == "space")

        def modifiers_ready() -> bool:
            if not modifiers:
                return True
            for modifier in modifiers:
                aliases = mod_aliases.get(modifier, {modifier})
                if not any(alias in held_mods for alias in aliases):
                    return False
            return True

        def on_press(key) -> None:
            name = key_name(key)
            if any(name in aliases for aliases in mod_aliases.values()):
                held_mods.add(name)
            if trigger_matches(name) and modifiers_ready():
                self._handle_press()

        def on_release(key) -> None:
            name = key_name(key)
            if any(name in aliases for aliases in mod_aliases.values()):
                held_mods.discard(name)
                if self._pressed:
                    self._handle_release()
            elif trigger_matches(name) and self._pressed:
                self._handle_release()

        def listen() -> None:
            logger.info("Hotkey listener active: hold '{}' to record.", self.hotkey)
            self._pynput_listener = pynput_keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            )
            self._pynput_listener.run()

        self._thread = threading.Thread(target=listen, daemon=True, name="hotkey-listener")
        self._thread.start()

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if _KEYBOARD_AVAILABLE:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        if self._pynput_listener is not None:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        logger.info("Hotkey listener {}.", "enabled" if self._enabled else "disabled")
