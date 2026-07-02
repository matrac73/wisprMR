"""Retrieve active app/window context for LLM tone hints."""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from loguru import logger

try:
    import psutil
except ImportError:
    psutil = None

try:
    import win32gui
    import win32process
    _WIN32_AVAILABLE = True
except ImportError:
    win32gui = None
    win32process = None
    _WIN32_AVAILABLE = False


def _run_osascript(script: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode != 0:
            logger.debug("osascript failed: {}", proc.stderr.strip())
            return None
        return proc.stdout.strip() or None
    except Exception as exc:
        logger.debug("osascript unavailable: {}", exc)
        return None


def get_active_process_name() -> Optional[str]:
    """
    Return the foreground app/process name.

    On macOS this uses System Events and may require Accessibility permission.
    """
    if sys.platform == "win32":
        if not (_WIN32_AVAILABLE and psutil is not None):
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name()
        except Exception as exc:
            logger.debug("Could not get foreground process: {}", exc)
            return None

    if sys.platform == "darwin":
        return _run_osascript(
            'tell application "System Events" to get name of first application process whose frontmost is true'
        )

    return None


def get_active_window_title() -> Optional[str]:
    """Return the foreground window title when the platform exposes it."""
    if sys.platform == "win32":
        if not _WIN32_AVAILABLE:
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd)
        except Exception as exc:
            logger.debug("Could not get window title: {}", exc)
            return None

    if sys.platform == "darwin":
        return _run_osascript(
            'tell application "System Events" to tell first application process whose frontmost is true to get name of front window'
        )

    return None
