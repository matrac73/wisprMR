"""System tray icon and menu (pystray + Pillow)."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_AVAILABLE = True
except ImportError:
    _TRAY_AVAILABLE = False
    logger.warning("pystray/Pillow not available — tray icon disabled.")


def _create_icon_image(color: str = "#4A90D9", size: int = 64) -> "Image.Image":
    """Generate a simple circular tray icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    margin = 4
    d.ellipse([margin, margin, size - margin, size - margin], fill=color)
    # Microphone shape
    cx, cy = size // 2, size // 2
    mic_w, mic_h = size // 6, size // 4
    d.rectangle(
        [cx - mic_w, cy - mic_h, cx + mic_w, cy + mic_h // 2],
        fill="white",
        outline=None,
    )
    d.arc(
        [cx - mic_w * 2, cy - mic_h // 2, cx + mic_w * 2, cy + mic_h],
        start=0,
        end=180,
        fill="white",
        width=2,
    )
    d.line([cx, cy + mic_h // 2, cx, cy + mic_h + 4], fill="white", width=2)
    return img


class TrayIcon:
    """
    System tray icon with context menu.

    Callbacks:
        on_toggle_enabled:  toggle push-to-talk on/off
        on_open_config:     open config.yaml in the default editor
        on_reload:          reload models / config
        on_quit:            shut down the app
    """

    def __init__(
        self,
        on_toggle_enabled: Optional[Callable[[], None]] = None,
        on_open_config: Optional[Callable[[], None]] = None,
        on_reload: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_toggle_enabled = on_toggle_enabled
        self.on_open_config = on_open_config
        self.on_reload = on_reload
        self.on_quit = on_quit
        self._enabled = True
        self._icon: Optional["pystray.Icon"] = None

    def _menu(self) -> "pystray.Menu":
        label = "Désactiver" if self._enabled else "Activer"
        return pystray.Menu(
            pystray.MenuItem(label, self._toggle),
            pystray.MenuItem("Ouvrir config.yaml", self._open_config),
            pystray.MenuItem("Recharger modèles", self._reload),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", self._quit),
        )

    def _toggle(self, _icon, _item) -> None:
        self._enabled = not self._enabled
        color = "#4A90D9" if self._enabled else "#888888"
        if self._icon:
            self._icon.icon = _create_icon_image(color)
            self._icon.menu = self._menu()
        if self.on_toggle_enabled:
            self.on_toggle_enabled()

    def _open_config(self, _icon, _item) -> None:
        if self.on_open_config:
            self.on_open_config()

    def _reload(self, _icon, _item) -> None:
        if self.on_reload:
            self.on_reload()

    def _quit(self, _icon, _item) -> None:
        if self._icon:
            self._icon.stop()
        if self.on_quit:
            self.on_quit()

    def start(self) -> None:
        """Run the tray icon in a background thread."""
        if not _TRAY_AVAILABLE:
            logger.warning("Tray icon unavailable.")
            return
        icon_img = _create_icon_image()
        self._icon = pystray.Icon(
            "wispr-mr",
            icon_img,
            "Wispr MR",
            menu=self._menu(),
        )
        t = threading.Thread(target=self._icon.run, daemon=True, name="tray")
        t.start()
        logger.info("Tray icon started.")

    def set_recording(self, recording: bool) -> None:
        """Change icon color to indicate active recording."""
        if self._icon and _TRAY_AVAILABLE:
            color = "#FF4040" if recording else ("#4A90D9" if self._enabled else "#888888")
            self._icon.icon = _create_icon_image(color)
