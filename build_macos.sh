#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYINSTALLER=".venv/bin/pyinstaller"
if [[ ! -x "$PYINSTALLER" ]]; then
  echo "PyInstaller introuvable: $PYINSTALLER"
  echo "Lance d'abord ./install_macos.sh"
  exit 1
fi

"$PYINSTALLER" \
  --clean \
  --onedir \
  --windowed \
  --name wispr_mr \
  --add-data "config.yaml:." \
  --add-data "dictionary.yaml:." \
  --hidden-import sounddevice \
  --hidden-import numpy \
  --hidden-import faster_whisper \
  --hidden-import ctranslate2 \
  --hidden-import onnxruntime \
  --hidden-import httpx \
  --hidden-import pyperclip \
  --hidden-import psutil \
  --hidden-import pystray \
  --hidden-import PIL \
  --hidden-import PySide6 \
  --hidden-import yaml \
  --hidden-import pydantic \
  --hidden-import loguru \
  --exclude-module torch \
  --exclude-module torchaudio \
  --exclude-module torchvision \
  --exclude-module silero_vad \
  app.py

echo
echo "Build complete. Output: dist/wispr_mr/"
echo "Run: dist/wispr_mr/wispr_mr.app"
