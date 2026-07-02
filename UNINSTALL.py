"""Unified uninstaller for Wispr MR.

Removes Wispr MR autostart entries, stops running app processes, and removes
local runtime/build folders created by installation. It does not uninstall
shared tools such as Python or Ollama.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def pause() -> None:
    if sys.stdin and sys.stdin.isatty():
        input("\nAppuie sur Entree pour fermer...")


def run(cmd: list[str], check: bool = False) -> int:
    print("+ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, check=False)
    if check and proc.returncode:
        raise RuntimeError(f"Commande echouee ({proc.returncode})")
    return proc.returncode


def remove_path(path: Path) -> None:
    if not path.exists():
        return
    print(f"Suppression: {path}")
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def cleanup_runtime() -> None:
    for name in (
        ".venv",
        "build",
        "dist",
        "logs",
        "__pycache__",
        "wispr_mr.spec",
        "WisprMR-Mac.zip",
    ):
        remove_path(ROOT / name)
    for cache in ROOT.rglob("__pycache__"):
        remove_path(cache)


def uninstall_windows() -> int:
    ps = ROOT / "autostart_install.ps1"
    if ps.exists():
        run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps),
                "-Remove",
            ]
        )

    # Stop python/pythonw processes running this app from this folder.
    current_pid = os.getpid()
    script = (
        "$root = "
        + repr(str(ROOT))
        + "; $currentPid = "
        + str(current_pid)
        + "; "
        + "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe' OR Name='wispr_mr.exe'\" "
        + "| Where-Object { $_.ProcessId -ne $currentPid -and $_.CommandLine -and $_.CommandLine -like \"*$root*\" } "
        + "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    run(["powershell", "-NoProfile", "-Command", script])
    cleanup_runtime()
    return 0


def uninstall_macos() -> int:
    plist = Path.home() / "Library" / "LaunchAgents" / "com.wisprmr.app.plist"
    if plist.exists():
        run(["launchctl", "unload", str(plist)])
        remove_path(plist)

    # Stop app processes launched from this folder.
    run(["pkill", "-f", str(ROOT / "app.py")])
    cleanup_runtime()
    return 0


def main() -> int:
    system = platform.system()
    print("============================================================")
    print("  Wispr MR - UNINSTALL")
    print("============================================================")
    print(f"Plateforme detectee : {system}")
    print()

    if system == "Windows":
        return uninstall_windows()
    if system == "Darwin":
        return uninstall_macos()

    print("Plateforme non supportee pour la desinstallation automatique.")
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
