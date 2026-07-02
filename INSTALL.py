"""Unified installer entry point for Wispr MR.

This is the only installer users should need to think about. It detects the
current OS and delegates to the platform-specific installer.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def pause() -> None:
    if sys.stdin and sys.stdin.isatty():
        input("\nAppuie sur Entree pour fermer...")


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def install_windows() -> int:
    script = ROOT / "setup.ps1"
    if not script.exists():
        print("ERREUR: setup.ps1 introuvable.")
        return 1
    return run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Profile",
            "balanced",
            "-Launch",
        ]
    )


def install_macos() -> int:
    script = ROOT / "install_macos.sh"
    if not script.exists():
        print("ERREUR: install_macos.sh introuvable.")
        return 1
    os.chmod(script, 0o755)
    return run(["/bin/bash", str(script), "balanced"])


def main() -> int:
    system = platform.system()
    print("============================================================")
    print("  Wispr MR - INSTALL")
    print("============================================================")
    print(f"Plateforme detectee : {system}")
    print()

    if system == "Windows":
        return install_windows()
    if system == "Darwin":
        return install_macos()

    print("Plateforme non supportee pour l'installation automatique.")
    print("Plateformes supportees : Windows et macOS.")
    return 1


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERREUR: {exc}")
        code = 1
    pause()
    raise SystemExit(code)
