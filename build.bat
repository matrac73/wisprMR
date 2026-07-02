@echo off
REM Build Wispr MR as a standalone directory (PyInstaller --onedir)
REM Run from the project root after install.bat/setup.ps1 created .venv.

echo Building Wispr MR...

set "PYINSTALLER=%~dp0.venv\Scripts\pyinstaller.exe"
if not exist "%PYINSTALLER%" (
  echo PyInstaller introuvable: %PYINSTALLER%
  echo Lance d'abord install.bat pour creer .venv et installer les dependances.
  exit /b 1
)

"%PYINSTALLER%" ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --name wispr_mr ^
  --noconsole ^
  --add-data "config.yaml;." ^
  --add-data "dictionary.yaml;." ^
  --hidden-import "sounddevice" ^
  --hidden-import "numpy" ^
  --hidden-import "faster_whisper" ^
  --hidden-import "ctranslate2" ^
  --hidden-import "onnxruntime" ^
  --hidden-import "httpx" ^
  --hidden-import "keyboard" ^
  --hidden-import "pyperclip" ^
  --hidden-import "win32gui" ^
  --hidden-import "win32process" ^
  --hidden-import "psutil" ^
  --hidden-import "pystray" ^
  --hidden-import "PIL" ^
  --hidden-import "PySide6" ^
  --hidden-import "yaml" ^
  --hidden-import "pydantic" ^
  --hidden-import "loguru" ^
  --exclude-module "torch" ^
  --exclude-module "torchaudio" ^
  --exclude-module "torchvision" ^
  --exclude-module "silero_vad" ^
  app.py

echo.
echo Build complete. Output: dist\wispr_mr\
echo Run: dist\wispr_mr\wispr_mr.exe
