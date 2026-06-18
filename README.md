# Wispr MR — Local Offline Voice Dictation (Windows, CPU)

100% local voice dictation inspired by Wispr Flow. Hold a hotkey, speak, release — text is inserted at your cursor in any Windows app within ~1 second. No cloud, no API keys, no GPU.

- **Speech-to-text:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`base` by default, int8 on CPU), transcribed **in streaming** while you speak so only the last fraction of a second is processed on release.
- **Text polish:** a small local LLM via [Ollama](https://ollama.com), applied **in the background** — raw text is inserted instantly, then replaced by the polished version a moment later (falls back to raw if offline).
- **Output:** clipboard paste into the focused window

---

## Requirements

- Windows 10 / 11
- [Python 3.11+](https://www.python.org/downloads/) (check **"Add python.exe to PATH"** during install)
- [Ollama](https://ollama.com) — optional but recommended for clean, punctuated output
- ~4 GB free RAM, no GPU required (CPU only)
- A working microphone

---

## Quick install (new PC)

```powershell
# 1. Get the code
git clone https://github.com/matrac73/wisprMR.git
cd wisprMR

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install Python dependencies (a few minutes on first run)
pip install -r requirements.txt
```

> If `git` is not installed, download the repo as a ZIP from GitHub and extract it,
> then run steps 2–3 from inside the extracted folder.

### Install Ollama and pull the LLM (recommended)

Download Ollama from <https://ollama.com>, then in a terminal:

```powershell
ollama pull qwen2.5:3b-instruct-q4_K_M     # default model
ollama pull qwen2.5:1.5b-instruct-q4_K_M   # lighter fallback
```

Keep Ollama running (the desktop app or `ollama serve`). If Ollama is unreachable, the app still works and inserts the raw Whisper transcription.

### Whisper model

The speech model downloads automatically from Hugging Face on first run (~1.5 GB, one time). No manual step needed — just be online the first time you run the app.

---

## Run

With the virtual environment activated:

```powershell
python app.py
```

The app starts minimised to the system tray. **Hold `Ctrl+Space`** to record, release to transcribe and insert at your cursor.

- Hover the small pill at the bottom of the screen to change **language**, **speed profile**, and toggle **LLM polish** live.
- Right-click the tray icon to quit or open the config.

---

## Configuration

Edit `config.yaml` and restart the app:

| Setting | What it does |
|---------|-------------|
| `profile` | `fast` (Whisper `base`, ≤1s — default) / `balanced` (`small`, ~2-3s) / `quality` (`large-v3-turbo`, slowest, most accurate). Override at launch with `python app.py --profile fast` |
| `hotkey` | Push-to-talk combination (default `ctrl+space`) |
| `stt.streaming` | Transcribe progressively during recording so release→insertion stays ~1s (default `true`) |
| `stt.language` | `null` = auto-detect, or force `"fr"` / `"en"` |
| `llm.enabled` | Turn the background LLM polish on/off |
| `llm.model` | Ollama model used for polishing |

> **Latency note (CPU-only laptops):** Whisper's heavier models are slow on low-power CPUs (e.g. an i7-1355U runs `large-v3-turbo` at ~2× *slower* than real time). To stay under 1 second, `fast`/`base` is the default; switch to `balanced`/`quality` only when you value raw accuracy over speed. The background LLM polish recovers much of the accuracy gap without adding perceived latency.

Add personal vocabulary fixes (names, jargon, acronyms) in `dictionary.yaml`.

---

## Start automatically with Windows (optional)

A helper script registers the app to launch silently at login:

```powershell
.\autostart_install.ps1            # install
.\autostart_install.ps1 -Remove    # uninstall
```

This creates a small launcher in your Windows Startup folder that runs the app
from this project's virtual environment. Run it once after setup is complete.

---

## Build a standalone executable (optional)

To produce a portable folder that runs without a Python install:

```powershell
build.bat
```

Output: `dist\wispr_mr\` — distribute the whole folder and run `wispr_mr.exe`.

---

## CLI test tools

```powershell
python tools/test_audio_capture.py            # dump mic audio to a WAV
python tools/test_transcribe.py path\to\file.wav   # transcribe + report latency
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **No audio captured** | Check the default microphone in Windows Sound Settings; set `audio.device` in `config.yaml` if needed. |
| **Hotkey not responding** | Run the terminal/app as administrator (some apps block global hotkeys). |
| **Ollama not reachable** | Make sure the Ollama app or `ollama serve` is running. Output falls back to raw text otherwise. |
| **High latency** | Make sure `profile: fast` (Whisper `base`) and `stt.streaming: true` in `config.yaml`. Heavier models (`small`/`turbo`) cannot hit ~1s on low-power CPUs. |
| **Overlay not showing** | Ensure PySide6 installed: `pip install PySide6==6.7.2`. |
| **First run is slow / downloads a lot** | Whisper downloads its model once (~1.5 GB). Subsequent runs are fast. |

---

## RAM budget

| Component | Est. RAM |
|-----------|---------|
| faster-whisper `large-v3-turbo` int8 | ~1.5 GB |
| `qwen2.5:3b` Q4_K_M (via Ollama) | ~2.0 GB |
| Python + libraries | ~200 MB |
| **Total** | **~3.7 GB** |

---

## How it works

```
Hotkey held → mic capture → VAD → faster-whisper (STT)
            → Ollama LLM polish (optional) → clipboard → paste at cursor
```

Everything runs locally on the CPU. No audio or text ever leaves the machine.
