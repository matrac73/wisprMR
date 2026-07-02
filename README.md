# Wispr MR - Local Offline Voice Dictation

Wispr MR is a local desktop dictation tool for Windows and macOS. Hold a hotkey,
speak, release: the text is transcribed locally, inserted at your cursor, then
optionally polished by a local Ollama model.

- **Speech-to-text:** faster-whisper on CPU, with streaming transcription while you speak.
- **Text polish:** optional local Ollama LLM, applied after raw insertion.
- **Desktop output:** clipboard paste into the focused app.
- **Mobile companion:** iPhone/Android can use the desktop engine from a browser on the same network and copy the resulting text.

Everything runs locally on the computer hosting Wispr MR. No cloud API key is required.

---

## Supported Platforms

| Platform | Status | Notes |
| --- | --- | --- |
| Windows 10/11 | Supported | Full push-to-talk, paste injection, tray/overlay, autostart. |
| macOS 13+ | Supported | Full push-to-talk and paste injection, requires macOS permissions. |
| iPhone / Android | Companion mode | Browser UI records/uploads audio to the desktop engine; global text injection into other phone apps is not available from a normal app/browser. |

---

## Requirements

- Python 3.11+
- Ollama, optional but recommended for polished output
- A working microphone
- About 4 GB free RAM for the quality profile; less for fast/balanced

On macOS, grant **Microphone**, **Accessibility**, and **Input Monitoring**
permissions when prompted. Without Accessibility/Input Monitoring, global hotkeys
and paste injection may be blocked by macOS.

---

## Quick Install

For normal users, only use the visible `INSTALL` / `UNINSTALL` files below.
The other scripts are internal helpers kept for packaging and troubleshooting.

### Windows

Double-click:

```powershell
install.bat
```

To uninstall:

```powershell
UNINSTALL.bat
```

### macOS

Double-click:

```text
INSTALL.command
```

To uninstall:

```text
UNINSTALL.command
```

The macOS installer creates `.venv`, installs dependencies, preloads the Whisper
model, and installs a LaunchAgent at:

```text
~/Library/LaunchAgents/com.wisprmr.app.plist
```

---

## Run

Windows:

```powershell
.\restart.ps1 -Profile balanced
```

macOS / manual:

```bash
.venv/bin/python app.py --profile balanced
```

Default hotkey:

```text
Ctrl+Space
```

You can change it in `config.yaml`. On macOS, `cmd+space` is usually reserved by
Spotlight, so prefer `ctrl+space`, `ctrl+shift+space`, or another custom combo.

---

## Configuration

Edit `config.yaml` and restart the app.

| Setting | What it does |
| --- | --- |
| `profile` | `fast`, `balanced`, or `quality`. |
| `hotkey` | Push-to-talk combination, for example `ctrl+space`. |
| `stt.streaming` | Transcribe progressively while recording. |
| `stt.language` | `null` for auto, or force `fr` / `en`. |
| `llm.enabled` | Enable/disable background LLM polish. |
| `llm.model` | Ollama model used for polishing. |

Add personal vocabulary fixes in `dictionary.yaml`.

---

## Build Desktop App

Windows:

```powershell
build.bat
```

Output:

```text
dist\wispr_mr\wispr_mr.exe
```

macOS:

```bash
./build_macos.sh
```

Output:

```text
dist/wispr_mr/
```

---

## iPhone / Android Companion Mode

Phones do not allow a normal third-party app or browser page to inject text
globally into every other app the way desktop Wispr MR can. The supported mobile
mode is therefore:

1. The phone records or uploads audio in a browser.
2. The desktop/mac running Wispr MR transcribes and polishes locally.
3. The phone receives copyable text.

Run on the computer:

```bash
python mobile_server.py --host 0.0.0.0 --port 8787 --profile balanced
```

Open on the phone, on the same Wi-Fi:

```text
http://<computer-ip>:8787
```

If direct recording is blocked because the browser wants HTTPS, use the audio
file/capture field on the page.

---

## CLI Test Tools

```bash
python tools/test_audio_capture.py
python tools/test_transcribe.py path/to/file.wav
```

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| No audio captured | Check microphone permissions and the default input device. |
| Hotkey not responding on Windows | Some apps require running Wispr MR as administrator. |
| Hotkey not responding on macOS | Grant Accessibility and Input Monitoring permissions. |
| Ollama not reachable | Start the Ollama app or run `ollama serve`. |
| High latency | Use `profile: fast` or `balanced`, and keep `stt.streaming: true`. |
| Overlay not showing | Check that PySide6 installed correctly. |

---

## How It Works

```text
Hotkey held -> mic capture -> faster-whisper STT
            -> optional Ollama polish -> clipboard paste
```
