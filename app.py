"""Wispr MR — local offline voice dictation app (CPU only)."""

from __future__ import annotations

import os
import sys
import threading
import time
import subprocess
from pathlib import Path
from typing import Optional

# Must be set before any Qt imports on Windows in this app.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from loguru import logger

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_config():
    """Load and validate configuration from config.yaml."""
    from config_loader import load_config

    return load_config()


# ---------------------------------------------------------------------------
# App orchestrator
# ---------------------------------------------------------------------------


class WisprApp:
    """Main application: wires all modules together and drives the event loop."""

    def __init__(self) -> None:
        self.cfg = None
        self._enabled = True
        self._pipeline_lock = threading.Lock()
        self._stream_session = None  # active StreamingSession during recording

        # Module instances (initialised in setup())
        self.audio = None
        self.transcriber = None
        self.polisher = None
        self.dictionary = None
        self.injector = None
        self.hotkey_listener = None
        self.overlay = None
        self.tray = None

    def setup(self, profile: Optional[str] = None) -> None:
        """Initialise all modules. Errors are logged but non-fatal where possible."""
        from config_loader import load_config

        self.cfg = load_config(profile=profile)
        self._configure_logging()

        active = profile or self.cfg.profile or "quality"
        logger.info("=== Wispr MR starting (profile: {}) ===", active)

        self._init_dictionary()
        self._init_audio()
        self._init_stt()
        self._init_llm()
        self._init_injector()
        self._init_hotkey()
        self._init_ui()

    def _configure_logging(self) -> None:
        log_cfg = self.cfg.logging
        log_path = Path(log_cfg.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.remove()
        # sys.stderr est None avec pythonw.exe (pas de console) — ne pas l'ajouter
        if sys.stderr is not None:
            logger.add(sys.stderr, level=log_cfg.level, colorize=True)
        logger.add(
            log_path,
            level=log_cfg.level,
            rotation=log_cfg.rotation,
            retention=log_cfg.retention,
            encoding="utf-8",
        )

    def _init_dictionary(self) -> None:
        from vocab.dictionary import VocabDictionary

        self.dictionary = VocabDictionary()

    def _init_audio(self) -> None:
        from audio.capture import AudioCapture

        a = self.cfg.audio
        self.audio = AudioCapture(
            sample_rate=a.sample_rate,
            preroll_ms=a.preroll_ms,
            max_record_s=a.max_record_s,
            device=a.device,
            rms_callback=self._on_rms,
        )
        try:
            self.audio.start_stream()
        except Exception as exc:
            logger.error(
                "Failed to start audio stream: {} — dictation unavailable.", exc
            )

    def _build_initial_prompt(self) -> Optional[str]:
        """Biaise Whisper vers le vocabulaire personnel (noms, jargon) pour
        améliorer la précision sur les termes du domaine."""
        if not self.dictionary or not self.dictionary.substitutions:
            return None
        terms = list(dict.fromkeys(self.dictionary.substitutions.values()))
        if not terms:
            return None
        return "Vocabulaire : " + ", ".join(terms) + "."

    def _init_stt(self) -> None:
        from stt.transcriber import Transcriber

        s = self.cfg.stt
        try:
            self.transcriber = Transcriber(
                model=s.model,
                compute_type=s.compute_type,
                cpu_threads=s.cpu_threads,
                language=s.language,
                beam_size=s.beam_size,
                best_of=s.best_of,
                initial_prompt=self._build_initial_prompt(),
            )
            self.transcriber.warmup()
        except Exception as exc:
            logger.error("STT init failed: {} — transcription unavailable.", exc)

    def _init_llm(self) -> None:
        if not self.cfg.llm.enabled:
            logger.info("LLM polish disabled in config.")
            return
        from llm.polisher import Polisher

        l = self.cfg.llm
        self.polisher = Polisher(
            base_url=l.base_url,
            model=l.model,
            fallback_model=l.fallback_model,
            timeout_s=l.timeout_s,
            min_chars=l.min_chars_for_polish,
            keep_alive=l.keep_alive,
            num_predict=l.num_predict,
            temperature=l.temperature,
            substitutions=self.dictionary.substitutions if self.dictionary else {},
        )
        if not self.polisher.ping():
            logger.warning(
                "Ollama not reachable at {} — LLM polish will fall back to raw text.",
                l.base_url,
            )
        else:
            self.polisher.warmup()

    def _init_injector(self) -> None:
        from inject.typer import TextInjector

        i = self.cfg.injection
        self.injector = TextInjector(
            method=i.method,
            paste_delay_ms=i.paste_delay_ms,
        )

    def _init_hotkey(self) -> None:
        from hotkey.listener import HotkeyListener

        self.hotkey_listener = HotkeyListener(
            hotkey=self.cfg.hotkey,
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release,
            on_cancel=self._on_hotkey_cancel,
            min_hold_ms=300,
        )
        self.hotkey_listener.start()

    def _init_ui(self) -> None:
        if self.cfg.ui.overlay:
            from ui.overlay import Overlay

            self.overlay = Overlay(
                get_settings=self._get_settings,
                apply_setting=self._apply_setting,
            )
        if self.cfg.ui.tray:
            from ui.tray import TrayIcon

            self.tray = TrayIcon(
                on_toggle_enabled=self._toggle_enabled,
                on_open_config=self._open_config,
                on_reload=self._reload,
                on_quit=self._quit,
            )
            self.tray.start()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_rms(self, rms: float) -> None:
        if self.overlay:
            self.overlay.set_rms(rms)

    def _on_hotkey_press(self) -> None:
        if not self._enabled:
            return
        if self.audio:
            self.audio.begin_recording()
            self._start_streaming()
        if self.overlay:
            from ui.overlay import OverlayState

            self.overlay.set_state(OverlayState.RECORDING)
        if self.tray:
            self.tray.set_recording(True)

    def _start_streaming(self) -> None:
        """Begin progressive transcription so most STT work happens while the
        user is still speaking (keeps release→insertion latency low)."""
        if not self.transcriber or not getattr(self.cfg.stt, "streaming", True):
            return
        # Defensively retire any session left over from a prior recording.
        if self._stream_session is not None:
            try:
                self._stream_session.cancel()
            except Exception:
                pass
            self._stream_session = None
        try:
            from stt.streaming import StreamingSession

            session = StreamingSession(
                self.transcriber, sample_rate=self.cfg.audio.sample_rate
            )
            # Seed with the pre-roll captured just before the key press.
            preroll = self.audio.preroll_snapshot()
            if preroll.size:
                session.feed(preroll)
            session.start()
            self._stream_session = session
            self.audio.set_live_consumer(session.feed)
        except Exception as exc:  # noqa: BLE001 — fall back to offline STT
            logger.warning("Streaming session failed to start: {}", exc)
            self._stream_session = None

    def _on_hotkey_release(self) -> None:
        if not self._enabled or not self.audio:
            return
        # Run pipeline in a background thread to avoid blocking the hotkey listener
        t = threading.Thread(target=self._run_pipeline, daemon=True, name="pipeline")
        t.start()

    def _on_hotkey_cancel(self) -> None:
        """Press was too short to be a real dictation — tear down cleanly so the
        streaming worker doesn't leak and the UI doesn't stay stuck on REC."""
        if self.audio:
            self.audio.set_live_consumer(None)
            self.audio.end_recording()  # reset recording state, discard audio
        session = self._stream_session
        self._stream_session = None
        if session:
            session.cancel()
        if self.tray:
            self.tray.set_recording(False)
        if self.overlay:
            from ui.overlay import OverlayState

            self.overlay.set_state(OverlayState.IDLE)

    def _run_pipeline(self) -> None:
        with self._pipeline_lock:
            try:
                self._pipeline()
            except Exception as exc:
                logger.exception("Unhandled pipeline error: {}", exc)
            finally:
                if self.tray:
                    self.tray.set_recording(False)
                if self.overlay:
                    from ui.overlay import OverlayState

                    time.sleep(0.8)
                    self.overlay.set_state(OverlayState.IDLE)

    def _pipeline(self) -> None:
        # Detach the streaming consumer and take ownership of the session.
        session = self._stream_session
        self._stream_session = None
        if self.audio:
            self.audio.set_live_consumer(None)

        # End capture (resets recording state; full audio is the offline fallback).
        audio = self.audio.end_recording()
        if len(audio) < self.cfg.audio.sample_rate * 0.3:
            logger.debug("Audio too short — ignoring.")
            if session:
                session.cancel()
            return

        # Active window context (for the LLM polish hint): process name + title,
        # ex. "Outlook.EXE — Re: Budget 2026". Aide le LLM a matcher le ton/registre.
        from context.active_window import get_active_process_name, get_active_window_title

        proc = get_active_process_name() or ""
        title = (get_active_window_title() or "").strip()[:80]
        ctx = f"{proc} — {title}" if proc and title else (proc or title)
        logger.debug("Active window context: {!r}", ctx)

        if not self.transcriber:
            logger.warning("No STT available.")
            if session:
                session.cancel()
            return

        if self.overlay:
            from ui.overlay import OverlayState

            self.overlay.set_state(OverlayState.TRANSCRIBING)

        # STT — streaming finishes the short tail; offline path transcribes all.
        t0 = time.perf_counter()
        if session is not None:
            raw_text = session.finish()
        else:
            raw_text = self.transcriber.transcribe(audio).text
        logger.info(
            "STT release→text: {:.2f}s | mode={} | text={!r}",
            time.perf_counter() - t0,
            "stream" if session is not None else "offline",
            raw_text[:80],
        )
        if not raw_text:
            logger.info("Empty transcription — nothing to inject.")
            return

        # Apply personal dictionary substitutions post-STT.
        if self.dictionary:
            raw_text = self.dictionary.apply(raw_text)

        if not self.injector:
            logger.warning("No injector available.")
            return

        # Insert the raw text IMMEDIATELY — this is where perceived latency ends.
        polish_active = (
            self.polisher is not None
            and getattr(self.polisher, "enabled", False)
            and len(raw_text) >= self.cfg.llm.min_chars_for_polish
        )
        if polish_active:
            self.injector.inject_raw(raw_text)
        else:
            self.injector.inject(raw_text)

        if self.overlay:
            from ui.overlay import OverlayState

            self.overlay.set_state(OverlayState.DONE)

        # Polish off the critical path: refine in the background, then replace.
        if polish_active:
            self._polish_and_replace(raw_text, ctx)

    def _polish_and_replace(self, raw_text: str, ctx: str) -> None:
        """Run the LLM polish after raw insertion and swap in the result."""
        if self.overlay:
            from ui.overlay import OverlayState

            self.overlay.set_state(OverlayState.POLISHING)
        polished = self.polisher.polish(raw_text, context_hint=ctx)
        if self.dictionary:
            polished = self.dictionary.apply(polished)
        # Guard against an LLM that ignored "output text only" and added prose.
        sane = polished and len(polished) <= len(raw_text) * 2 + 40
        if sane and polished != raw_text:
            self.injector.replace_with_polished(polished)
        elif not sane:
            logger.warning("Polish output looks off — keeping raw text.")
        if self.overlay:
            from ui.overlay import OverlayState

            self.overlay.set_state(OverlayState.DONE)

    # ------------------------------------------------------------------
    # Tray actions
    # ------------------------------------------------------------------

    def _toggle_enabled(self) -> None:
        self._enabled = not self._enabled
        if self.hotkey_listener:
            self.hotkey_listener.set_enabled(self._enabled)
        logger.info("Dictation {}.", "enabled" if self._enabled else "disabled")

    # ------------------------------------------------------------------
    # Réglages live (panneau de l'overlay)
    # ------------------------------------------------------------------

    def _get_settings(self) -> dict:
        """Snapshot des réglages courants pour alimenter le panneau."""
        polish = self.polisher is not None and getattr(
            self.polisher, "enabled", False
        )
        return {
            "profile": (self.cfg.profile if self.cfg else None) or "balanced",
            "polish": polish,
            "language": self.cfg.stt.language if self.cfg else None,
            "hotkey": self.cfg.hotkey if self.cfg else "—",
        }

    def _apply_setting(self, key: str, value) -> None:
        """Applique un réglage en direct + persiste dans config.yaml.

        Appelé depuis le thread Qt — les opérations lourdes (rechargement de
        modèle) partent en thread dédié pour ne pas figer l'UI.
        """
        try:
            if key == "polish":
                self._apply_polish(bool(value))
            elif key == "language":
                self._apply_language(value)
            elif key == "profile":
                self._apply_profile(str(value))
            else:
                return
            self._persist_setting(key, value)
        except Exception as exc:
            logger.exception("apply_setting({}={}) failed: {}", key, value, exc)

    def _persist_setting(self, key: str, value) -> None:
        from config_loader import update_config_file

        dotted = {
            "polish": "llm.enabled",
            "language": "stt.language",
            "profile": "profile",
        }.get(key)
        if dotted:
            update_config_file({dotted: value})

    def _apply_polish(self, enabled: bool) -> None:
        if self.polisher is not None:
            self.polisher.set_enabled(enabled)
        elif enabled:
            # Polish désactivé au démarrage → instanciation à la demande.
            # _init_llm() ping + warmup Ollama (jusqu'à 120s) → en thread pour
            # ne pas figer l'UI Qt.
            self.cfg.llm.enabled = True

            def _build() -> None:
                if self.overlay:
                    self.overlay.set_busy("chargement IA…")
                try:
                    self._init_llm()
                finally:
                    if self.overlay:
                        self.overlay.set_busy(None)

            threading.Thread(target=_build, daemon=True, name="llm-init").start()
        logger.info("Polish {} (live).", "on" if enabled else "off")

    def _apply_language(self, value) -> None:
        lang = value or None
        if self.cfg:
            self.cfg.stt.language = lang
        if self.transcriber:
            self.transcriber.set_language(lang)

    def _apply_profile(self, profile: str) -> None:
        from config_loader import PROFILES

        preset = PROFILES.get(profile)
        if not preset:
            return
        if self.cfg:
            self.cfg.profile = profile

        stt = preset.get("stt", {})
        llm = preset.get("llm", {})
        model = stt.get("model")
        beam = stt.get("beam_size")
        best = stt.get("best_of")
        llm_model = llm.get("model")

        def _reload() -> None:
            if self.overlay:
                self.overlay.set_busy("chargement modèle…")
            try:
                if self.transcriber and model:
                    self.transcriber.reload_model(model, beam, best)
                if self.polisher and llm_model:
                    self.polisher.set_model(llm_model)
                logger.info("Profil '{}' appliqué (live).", profile)
            except Exception as exc:
                logger.exception("Profile reload failed: {}", exc)
            finally:
                if self.overlay:
                    self.overlay.set_busy(None)

        threading.Thread(target=_reload, daemon=True, name="profile-reload").start()

    def _open_config(self) -> None:
        path = str(Path("config.yaml").resolve())
        if sys.platform == "win32":
            subprocess.Popen(["notepad", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _reload(self) -> None:
        logger.info("Reload requested — restarting app.")
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def _quit(self) -> None:
        logger.info("Quitting.")
        if self.audio:
            self.audio.stop_stream()
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        sys.exit(0)

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the Qt event loop (blocks until quit)."""
        if self.cfg.ui.overlay:
            try:
                from PySide6.QtWidgets import QApplication

                app = QApplication.instance() or QApplication(sys.argv)
                if self.overlay:
                    self.overlay.init_window()
                logger.info("Qt event loop starting.")
                sys.exit(app.exec())
            except Exception as exc:
                logger.error("Qt event loop failed: {} — running without overlay.", exc)
                self._run_headless()
        else:
            self._run_headless()

    def _run_headless(self) -> None:
        """Headless mode: just keep the main thread alive."""
        logger.info("Running headless (no overlay). Press Ctrl+C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self._quit()


def _parse_args() -> dict:
    import argparse

    parser = argparse.ArgumentParser(description="Wispr MR — local voice dictation")
    parser.add_argument(
        "--profile",
        choices=["fast", "balanced", "quality"],
        default=None,
        help="Profil de vitesse (surcharge config.yaml) : fast | balanced | quality",
    )
    return vars(parser.parse_args())


# Handle global gardé vivant pour la durée du process (verrou instance unique).
_SINGLE_INSTANCE_HANDLE = None


def _acquire_single_instance_lock() -> bool:
    """Empêche plusieurs instances de Wispr MR de tourner en parallèle.

    Utilise un mutex Windows nommé, libéré automatiquement à la mort du
    process. Retourne False si une instance tourne déjà.
    """
    global _SINGLE_INSTANCE_HANDLE
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "WisprMR_SingleInstance")
        if not handle:
            return True  # en cas d'échec on ne bloque pas le démarrage
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        _SINGLE_INSTANCE_HANDLE = handle  # garder le handle vivant
        return True
    except Exception:
        return True


def main() -> None:
    if not _acquire_single_instance_lock():
        logger.warning(
            "Une instance de Wispr MR est déjà en cours — sortie immédiate."
        )
        sys.exit(0)

    args = _parse_args()
    profile = args.get("profile")

    app = WisprApp()
    try:
        app.setup(profile=profile)
    except Exception as exc:
        logger.exception("Fatal error during setup: {}", exc)
        sys.exit(1)
    app.run()


if __name__ == "__main__":
    main()
