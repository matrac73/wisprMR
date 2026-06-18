"""Push-to-talk hotkey listener (hold = record, release = stop)."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from loguru import logger

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except ImportError:
    _KEYBOARD_AVAILABLE = False

try:
    from pynput import keyboard as pynput_keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False


class HotkeyListener:
    """
    Listens for a configurable hold-hotkey (default: ctrl+space).

    on_press:   called when the key combination is first held down.
    on_release: called when the key combination is released.

    Debounce: releases within min_hold_ms are ignored (too short).
    Uses the 'keyboard' library; falls back to 'pynput' if unavailable.
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
        # Called when a press is released too quickly (below min_hold_ms) so the
        # app can tear down anything on_press started (e.g. a streaming session).
        self.on_cancel = on_cancel
        self.min_hold_ms = min_hold_ms

        self._pressed = False
        self._press_time: float = 0.0
        self._enabled = True
        self._thread: Optional[threading.Thread] = None

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
            logger.debug("Hotkey held only {:.0f}ms — ignoring (too short).", held_ms)
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
        """Parse 'ctrl+shift+space' → ({'ctrl', 'shift'}, 'space')."""
        parts = [p.strip().lower() for p in self.hotkey.split("+")]
        trigger = parts[-1]
        modifiers = set(parts[:-1])
        return modifiers, trigger

    def start(self) -> None:
        """Start listening in a background thread."""
        if not _KEYBOARD_AVAILABLE:
            logger.error("'keyboard' library not available — hotkey disabled.")
            return

        modifiers, trigger = self._parse_hotkey()

        # Noms canoniques des modificateurs reconnus par `keyboard`
        _MOD_ALIASES: dict[str, set[str]] = {
            "ctrl":  {"ctrl", "left ctrl", "right ctrl"},
            "shift": {"shift", "left shift", "right shift"},
            "alt":   {"alt", "left alt", "right alt"},
            "win":   {"windows", "left windows", "right windows"},
        }
        mod_names: set[str] = set()
        for m in modifiers:
            mod_names |= _MOD_ALIASES.get(m, {m})

        held_mods: set[str] = set()

        def _on_event(event: "keyboard.KeyboardEvent") -> None:
            name = event.name.lower() if event.name else ""

            # Suivre l'état des modificateurs
            if name in mod_names:
                if event.event_type == keyboard.KEY_DOWN:
                    held_mods.add(name)
                else:
                    held_mods.discard(name)
                    # Relâcher un modificateur pendant l'enregistrement = stop
                    if self._pressed:
                        self._handle_release()
                return

            # Touche déclencheur
            if name == trigger:
                if event.event_type == keyboard.KEY_DOWN:
                    # Vérifier que tous les modificateurs sont enfoncés
                    mods_held = any(
                        any(alias in held_mods for alias in _MOD_ALIASES.get(m, {m}))
                        for m in modifiers
                    ) if modifiers else True
                    if mods_held:
                        self._handle_press()
                elif event.event_type == keyboard.KEY_UP:
                    if self._pressed:
                        self._handle_release()

        def _listen() -> None:
            keyboard.hook(_on_event)
            logger.info("Hotkey listener active: hold '{}' to record.", self.hotkey)
            keyboard.wait()

        self._thread = threading.Thread(target=_listen, daemon=True, name="hotkey-listener")
        self._thread.start()

    def stop(self) -> None:
        """Stop the hotkey listener."""
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        logger.info("Hotkey listener {}.", "enabled" if enabled else "disabled")
