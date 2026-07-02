#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PROFILE="${1:-balanced}"
if [[ "$PROFILE" != "fast" && "$PROFILE" != "balanced" && "$PROFILE" != "quality" ]]; then
  echo "Usage: ./install_macos.sh [fast|balanced|quality]"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 introuvable. Installe Python 3.11+ ou Homebrew puis relance."
  exit 1
fi

PYTHON_BIN="$(command -v python3)"
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ requis")
PY

echo "==> Creation de .venv"
"$PYTHON_BIN" -m venv .venv

echo "==> Installation des dependances Python"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if ! command -v ollama >/dev/null 2>&1; then
  echo "==> Ollama introuvable."
  echo "    Installe Ollama pour macOS depuis https://ollama.com/download, puis relance ce script."
else
  echo "==> Pull modeles Ollama"
  ollama pull qwen2.5:1.5b-instruct-q4_K_M || true
  ollama pull qwen2.5:3b-instruct-q4_K_M || true
fi

echo "==> Prechargement Whisper ($PROFILE)"
.venv/bin/python - <<PY
import sys
sys.path.insert(0, ".")
from config_loader import PROFILES
from stt.transcriber import _resolve_model_name
from faster_whisper import WhisperModel

name = PROFILES["$PROFILE"]["stt"]["model"]
model = _resolve_model_name(name)
print(f"[whisper] telechargement de {model}...")
WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=1, num_workers=1)
print("[whisper] pret.")
PY

echo "==> Installation LaunchAgent"
mkdir -p "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/com.wisprmr.app.plist"
PROJECT_DIR="$(pwd)"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.wisprmr.app</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT_DIR/.venv/bin/python</string>
    <string>$PROJECT_DIR/app.py</string>
    <string>--profile</string>
    <string>$PROFILE</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"

echo
echo "[OK] Wispr MR installe sur macOS."
echo "     Lance maintenant : .venv/bin/python app.py --profile $PROFILE"
echo "     Permissions macOS a accorder si demandees : Microphone, Accessibility, Input Monitoring."
