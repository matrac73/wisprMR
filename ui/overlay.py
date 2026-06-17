"""Floating status indicator — translucent, discreet, hover-interactive.

Au repos : une pastille translucide et discrète en bas de l'écran (click-through,
ne gêne jamais les clics). Au survol de la souris, elle s'étend en un panneau de
réglages permettant de configurer en direct le profil/modèle, l'activation du
polish IA et la langue de transcription.
"""
from __future__ import annotations

import sys
import threading
import time
from enum import Enum, auto
from typing import Callable, Optional

from loguru import logger

try:
    from PySide6.QtCore import (
        Qt,
        QTimer,
        QRect,
        QRectF,
        Signal,
        QPropertyAnimation,
        QEasingCurve,
    )
    from PySide6.QtGui import (
        QColor,
        QPainter,
        QFont,
        QPainterPath,
        QCursor,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QWidget,
        QComboBox,
        QFrame,
        QLabel,
        QVBoxLayout,
        QHBoxLayout,
        QGraphicsOpacityEffect,
    )

    _PYSIDE6_AVAILABLE = True
except ImportError:
    _PYSIDE6_AVAILABLE = False
    logger.warning("PySide6 not available — overlay disabled.")


# ── Win32 : click-through dynamique sans scintillement ──────────────────────


def _set_click_through(hwnd: int, enabled: bool) -> None:
    """Active/désactive le passe-clic (WS_EX_TRANSPARENT) sur Windows."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception as exc:  # noqa: BLE001
        logger.debug("click-through toggle failed: {}", exc)


class OverlayState(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()
    POLISHING = auto()
    DONE = auto()


# ── Design tokens ───────────────────────────────────────────────────────────

# Trois tailles : minuscule au repos, moyenne pendant l'activité, grande au survol.
_IDLE_W, _IDLE_H = 54, 20         # pastille discrète au repos (juste un point)
_ACTIVE_W, _ACTIVE_H = 208, 36    # pendant rec / transcription / polish
_PANEL_W = 320                    # largeur du panneau de réglages (survol)
_PANEL_H = 196
_STATUS_H = 44                    # bande de statut sous le panneau (mode étendu)
_EXPANDED_H = _STATUS_H + _PANEL_H
_BOTTOM_MARGIN = 64               # distance du bas de l'écran
_PAD = 13
_RADIUS = 13

_BG = QColor(16, 16, 18)            # carte quasi-noire
_BORDER = QColor(255, 255, 255, 26)
_TEXT = QColor(214, 214, 218)
_TEXT_DIM = QColor(150, 150, 156)

_VU_BLOCKS = 8
_VU_BW = 4
_VU_BH = 16
_VU_GAP = 3
_VU_TOTAL_W = _VU_BLOCKS * (_VU_BW + _VU_GAP) - _VU_GAP

_LABELS: dict = {}
_ACCENT: dict = {}

_COLLAPSE_DELAY_S = 0.35     # hystérésis avant repli après sortie souris

# Choix proposés dans les menus déroulants
_PROFILE_ITEMS = [("Rapide", "fast"), ("Équilibré", "balanced"), ("Qualité", "quality")]
_LANG_ITEMS = [("Auto", None), ("Français", "fr"), ("English", "en")]


if _PYSIDE6_AVAILABLE:

    _LABELS = {
        OverlayState.IDLE: "prêt",
        OverlayState.RECORDING: "rec",
        OverlayState.TRANSCRIBING: "transcription…",
        OverlayState.POLISHING: "polish…",
        OverlayState.DONE: "inséré",
    }

    def _init_accents() -> None:
        global _ACCENT
        _ACCENT = {
            OverlayState.IDLE: QColor(110, 110, 118),
            OverlayState.RECORDING: QColor(239, 68, 68),
            OverlayState.TRANSCRIBING: QColor(245, 158, 11),
            OverlayState.POLISHING: QColor(96, 165, 250),
            OverlayState.DONE: QColor(34, 197, 94),
        }

    _PANEL_QSS = """
        QFrame#panel { background: transparent; }
        QLabel { color: #c9c9cf; font-family: 'Segoe UI'; font-size: 12px;
                 background: transparent; }
        QLabel#title { color: #8a8a92; font-size: 10px; font-weight: 600;
                       letter-spacing: 2px; }
        QComboBox { background: rgba(255,255,255,0.07); color: #e8e8ec;
                    border: 1px solid rgba(255,255,255,0.12); border-radius: 7px;
                    padding: 4px 10px; font-family: 'Segoe UI'; font-size: 12px;
                    min-width: 118px; }
        QComboBox:hover { background: rgba(255,255,255,0.13); }
        QComboBox::drop-down { border: none; width: 18px; }
        QComboBox QAbstractItemView {
            background: #1c1c20; color: #e8e8ec; outline: none;
            border: 1px solid rgba(255,255,255,0.14); border-radius: 8px;
            selection-background-color: rgba(96,165,250,0.35);
            padding: 4px; }
    """

    class _ToggleSwitch(QWidget):
        """Petit interrupteur à bascule peint à la main."""

        toggled = Signal(bool)

        def __init__(self, checked: bool = False) -> None:
            super().__init__()
            self._checked = checked
            self.setFixedSize(40, 22)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        def isChecked(self) -> bool:
            return self._checked

        def setChecked(self, value: bool) -> None:
            if value != self._checked:
                self._checked = value
                self.update()

        def mousePressEvent(self, _e) -> None:  # type: ignore[override]
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)

        def paintEvent(self, _e) -> None:  # type: ignore[override]
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            track = QColor(96, 165, 250) if self._checked else QColor(74, 74, 82)
            p.setBrush(track)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 11, 11)
            d = 16
            x = self.width() - d - 3 if self._checked else 3
            p.setBrush(QColor(245, 245, 247))
            p.drawEllipse(QRectF(x, 3, d, d))
            p.end()

    class OverlayWindow(QWidget):
        """Fenêtre frameless translucide, always-on-top, hover-interactive."""

        def __init__(
            self,
            get_settings: Optional[Callable[[], dict]] = None,
            apply_setting: Optional[Callable[[str, object], None]] = None,
        ) -> None:
            super().__init__()
            _init_accents()
            self._get_settings = get_settings
            self._apply_setting = apply_setting

            self._state = OverlayState.IDLE
            self._rms = 0.0
            self._lock = threading.Lock()
            self._pending_state: Optional[OverlayState] = None
            self._pending_rms: float = 0.0
            self._busy_msg: Optional[str] = None

            self._expanded = False
            self._leave_at: Optional[float] = None
            self._click_through = True
            self._applied_size: tuple = (0, 0)

            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

            self._build_panel()
            self._apply_geometry()

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(33)  # ~30 fps

        # ── Construction du panneau de réglages ────────────────────────────

        def _build_panel(self) -> None:
            self.panel = QFrame(self)
            self.panel.setObjectName("panel")
            self.panel.setStyleSheet(_PANEL_QSS)
            self.panel.setGeometry(0, 0, _PANEL_W, _PANEL_H)

            lay = QVBoxLayout(self.panel)
            lay.setContentsMargins(_PAD + 4, _PAD, _PAD + 4, _PAD)
            lay.setSpacing(11)

            title = QLabel("WISPR · RÉGLAGES")
            title.setObjectName("title")
            lay.addWidget(title)

            # Profil / modèle
            self.profile_combo = QComboBox()
            for label, _val in _PROFILE_ITEMS:
                self.profile_combo.addItem(label)
            lay.addLayout(self._row("Profil", self.profile_combo))

            # Polish IA
            self.polish_toggle = _ToggleSwitch(checked=True)
            lay.addLayout(self._row("Polish IA", self.polish_toggle))

            # Langue
            self.lang_combo = QComboBox()
            for label, _val in _LANG_ITEMS:
                self.lang_combo.addItem(label)
            lay.addLayout(self._row("Langue", self.lang_combo))

            # Raccourci (lecture seule)
            self.hotkey_label = QLabel("—")
            self.hotkey_label.setStyleSheet("color:#7d7d85; font-size:11px;")
            lay.addLayout(self._row("Raccourci", self.hotkey_label))

            lay.addStretch(1)

            # Effet d'opacité pour le fondu d'apparition
            self._panel_fx = QGraphicsOpacityEffect(self.panel)
            self._panel_fx.setOpacity(0.0)
            self.panel.setGraphicsEffect(self._panel_fx)
            self._panel_anim = QPropertyAnimation(self._panel_fx, b"opacity", self)
            self._panel_anim.setDuration(130)
            self._panel_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.panel.setVisible(False)

            self._load_settings_into_panel()

            # Connecter APRÈS chargement initial pour ne pas déclencher d'écriture
            self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
            self.polish_toggle.toggled.connect(self._on_polish_toggled)
            self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)

        def _row(self, label_text: str, control: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            row.addWidget(lbl)
            row.addStretch(1)
            row.addWidget(control)
            return row

        def _load_settings_into_panel(self) -> None:
            if not self._get_settings:
                return
            try:
                s = self._get_settings()
            except Exception as exc:  # noqa: BLE001
                logger.debug("get_settings failed: {}", exc)
                return
            prof = s.get("profile") or "balanced"
            idx = next(
                (i for i, (_l, v) in enumerate(_PROFILE_ITEMS) if v == prof), 1
            )
            self.profile_combo.setCurrentIndex(idx)
            self.polish_toggle.setChecked(bool(s.get("polish", True)))
            lang = s.get("language")
            lidx = next(
                (i for i, (_l, v) in enumerate(_LANG_ITEMS) if v == lang), 0
            )
            self.lang_combo.setCurrentIndex(lidx)
            self.hotkey_label.setText(str(s.get("hotkey", "—")))

        # ── Handlers de réglages ───────────────────────────────────────────

        def _on_profile_changed(self, idx: int) -> None:
            if self._apply_setting and 0 <= idx < len(_PROFILE_ITEMS):
                self._apply_setting("profile", _PROFILE_ITEMS[idx][1])

        def _on_polish_toggled(self, checked: bool) -> None:
            if self._apply_setting:
                self._apply_setting("polish", checked)

        def _on_lang_changed(self, idx: int) -> None:
            if self._apply_setting and 0 <= idx < len(_LANG_ITEMS):
                self._apply_setting("language", _LANG_ITEMS[idx][1])

        # ── Géométrie / position ───────────────────────────────────────────

        def _target_size(self) -> tuple:
            """Taille cible selon l'état : minuscule au repos, moyenne en
            activité, grande au survol."""
            if self._expanded:
                return (_PANEL_W, _EXPANDED_H)
            if self._state != OverlayState.IDLE:
                return (_ACTIVE_W, _ACTIVE_H)
            return (_IDLE_W, _IDLE_H)

        def _apply_geometry(self) -> None:
            """Applique la taille cible, ancrée en bas-centre (le bord bas
            reste fixe, la fenêtre grandit vers le haut)."""
            w, h = self._target_size()
            if (w, h) == self._applied_size:
                return
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - w) // 2
            y = screen.y() + screen.height() - _BOTTOM_MARGIN - h
            self.setFixedSize(w, h)
            self.move(x, y)
            self._applied_size = (w, h)

        # ── API thread-safe ────────────────────────────────────────────────

        def set_state(self, state: OverlayState) -> None:
            with self._lock:
                self._pending_state = state

        def set_rms(self, rms: float) -> None:
            with self._lock:
                self._pending_rms = min(rms * 10, 1.0)

        def set_busy(self, msg: Optional[str]) -> None:
            """Message transitoire (ex. 'chargement modèle…')."""
            with self._lock:
                self._busy_msg = msg

        # ── Expansion / repli ──────────────────────────────────────────────

        def _set_click_through(self, enabled: bool) -> None:
            if enabled == self._click_through:
                return
            self._click_through = enabled
            _set_click_through(int(self.winId()), enabled)

        def _expand(self) -> None:
            if self._expanded:
                return
            self._expanded = True
            self._load_settings_into_panel()
            self._apply_geometry()
            self.panel.setVisible(True)
            self._set_click_through(False)
            self._panel_anim.stop()
            self._panel_anim.setStartValue(self._panel_fx.opacity())
            self._panel_anim.setEndValue(1.0)
            self._panel_anim.start()

        def _collapse(self) -> None:
            if not self._expanded:
                return
            self._expanded = False
            self.panel.setVisible(False)
            self._panel_fx.setOpacity(0.0)
            self._apply_geometry()
            self._set_click_through(True)

        # ── Timer (main thread) ────────────────────────────────────────────

        def _tick(self) -> None:
            with self._lock:
                pending = self._pending_state
                self._pending_state = None
                self._rms = self._pending_rms

            if pending is not None:
                self._state = pending
                if not self.isVisible():
                    self.show()
                    self._set_click_through(True)

            # Détection de survol (hystérésis pour éviter le clignotement)
            cur = QCursor.pos()
            inside = self.geometry().contains(cur)
            now = time.monotonic()
            if inside:
                self._leave_at = None
                if not self._expanded:
                    self._expand()
            elif self._expanded:
                if self._leave_at is None:
                    self._leave_at = now
                elif now - self._leave_at > _COLLAPSE_DELAY_S:
                    self._collapse()

            # Ajuste la taille si l'état a changé hors survol (no-op si stable)
            if not self._expanded:
                self._apply_geometry()

            self.update()

        # ── Rendu ──────────────────────────────────────────────────────────

        def paintEvent(self, _event) -> None:  # type: ignore[override]
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            w, h = self.width(), self.height()
            active = self._state != OverlayState.IDLE
            base_alpha = 246 if (active or self._expanded) else 165

            # Carte / pastille translucide arrondie (radius cappé à h/2)
            r = min(float(_RADIUS), h / 2.0)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
            bg = QColor(_BG)
            bg.setAlpha(base_alpha)
            p.fillPath(path, bg)
            p.setPen(_BORDER)
            p.drawPath(path)

            # Bande de statut (occupe toute la fenêtre sauf en mode étendu)
            strip_h = _STATUS_H if self._expanded else h
            self._paint_status(p, h - strip_h, strip_h, w, active)
            p.end()

        def _paint_status(
            self, p: QPainter, top: int, strip_h: int, w: int, active: bool
        ) -> None:
            accent = QColor(_ACCENT.get(self._state, _ACCENT[OverlayState.IDLE]))
            cy = top + strip_h // 2

            # Repos & non survolé → simple point centré, ultra discret
            if self._state == OverlayState.IDLE and not self._expanded:
                p.setBrush(accent)
                p.setPen(Qt.PenStyle.NoPen)
                rr = 3.5
                p.drawEllipse(QRectF(w / 2 - rr, cy - rr, rr * 2, rr * 2))
                return

            # Point d'état (à gauche)
            dot_x = _PAD
            p.setBrush(accent)
            p.setPen(Qt.PenStyle.NoPen)
            dot_r = 5 if self._state == OverlayState.RECORDING else 4
            p.drawEllipse(QRect(dot_x, cy - dot_r, dot_r * 2, dot_r * 2))

            # Libellé
            with self._lock:
                busy = self._busy_msg
            label = busy or _LABELS.get(self._state, "")
            font = QFont("Segoe UI", 10)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
            p.setFont(font)
            p.setPen(_TEXT if active or busy else _TEXT_DIM)
            text_x = dot_x + dot_r * 2 + 10
            recording = self._state == OverlayState.RECORDING
            right_reserve = (_VU_TOTAL_W + _PAD + 6) if recording else _PAD
            text_rect = QRect(text_x, top, w - text_x - right_reserve, strip_h)
            p.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                label,
            )

            # VU-mètre pendant l'enregistrement
            if recording:
                vu_x = w - _VU_TOTAL_W - _PAD
                vu_y = cy - _VU_BH // 2
                n_active = round(self._rms * _VU_BLOCKS)
                for i in range(_VU_BLOCKS):
                    x = vu_x + i * (_VU_BW + _VU_GAP)
                    if i < n_active:
                        intensity = 170 + int(85 * i / max(_VU_BLOCKS - 1, 1))
                        c = QColor(accent)
                        c.setAlpha(intensity)
                    else:
                        c = QColor(40, 40, 44, 200)
                    p.fillRect(x, vu_y, _VU_BW, _VU_BH, c)

    # ── Wrapper public ──────────────────────────────────────────────────────

    class Overlay:
        """Proxy thread-safe vers OverlayWindow."""

        def __init__(
            self,
            get_settings: Optional[Callable[[], dict]] = None,
            apply_setting: Optional[Callable[[str, object], None]] = None,
        ) -> None:
            self._window: Optional[OverlayWindow] = None
            self._get_settings = get_settings
            self._apply_setting = apply_setting

        def init_window(self) -> None:
            """À appeler depuis le thread Qt principal."""
            self._window = OverlayWindow(self._get_settings, self._apply_setting)
            self._window.show()
            self._window._set_click_through(True)

        def set_state(self, state: OverlayState) -> None:
            if self._window:
                self._window.set_state(state)

        def set_rms(self, rms: float) -> None:
            if self._window:
                self._window.set_rms(rms)

        def set_busy(self, msg: Optional[str]) -> None:
            if self._window:
                self._window.set_busy(msg)

else:

    class Overlay:  # type: ignore[no-redef]
        def __init__(self, *_a, **_k) -> None: ...
        def init_window(self) -> None: ...
        def set_state(self, state: "OverlayState") -> None: ...
        def set_rms(self, rms: float) -> None: ...
        def set_busy(self, msg: Optional[str]) -> None: ...
