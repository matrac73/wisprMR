"""Retrieve the name of the currently active (foreground) Windows process."""
from __future__ import annotations

from typing import Optional

from loguru import logger

try:
    import win32gui
    import win32process
    import psutil
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False
    logger.warning("pywin32/psutil not available — active window detection disabled.")


def get_active_process_name() -> Optional[str]:
    """
    Return the executable name of the foreground window process, e.g. 'notepad.exe'.

    Returns None if detection is unavailable or fails.
    """
    if not _WIN32_AVAILABLE:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        return proc.name()
    except Exception as exc:
        logger.debug("Could not get foreground process: {}", exc)
        return None


def get_active_window_title() -> Optional[str]:
    """Return the title bar text of the foreground window."""
    if not _WIN32_AVAILABLE:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd)
    except Exception as exc:
        logger.debug("Could not get window title: {}", exc)
        return None
