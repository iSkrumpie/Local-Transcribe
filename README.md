# Local Transcribe

**Local-first, browser-based push-to-talk speech-to-text — runs on Linux, macOS, and Windows.**
Press <kbd>Space</kbd> → speak → watch the text grow in the textarea → press <kbd>.</kbd> to finalize.

| | Backend | Devices |
|---|---|---|
| **macOS Apple Silicon** | [`mlx-whisper`](https://github.com/mlx-whisper/mlx-whisper) | GPU/NPU (~9× real-time) |
| **Linux / Windows / Intel macOS** | [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) | CPU or CUDA |

No cloud, no API keys, no telemetry. ~9× real-time on Apple Silicon; ~3× on a modern CPU; faster with a CUDA GPU.

---

## ✨ Features

- 🎙️ **Push-to-talk** — <kbd>Space</kbd> to record/pause, <kbd>.</kbd> to stop & finalize
- ⚡ **Live transcription** — text grows in the textarea in real time as you speak (`~1.5 s` updates)
- 🌐 **Multilingual** — Whisper auto-detects English, German, and 97 other languages
- 🌓 **Dark theme**, modern minimalist UI
- ✏️ **Editable transcript** — your edits are preserved (caret-aware)
- 📋 **One-click copy** to clipboard
- 🔒 **Fully local** — no network calls once the model is downloaded
- 🪟 **Cross-platform** — runs on Linux, macOS, and Windows from the same codebase

---

## 🏗️ Architecture

```
Browser (http://localhost:8000)
  │
  │   MediaRecorder → webm/opus chunks every 750 ms
  │   (kept in memory, concatenated on each send)
  │
  └─ WebSocket /ws/transcribe  → complete-so-far webm blob every 1.5 s
                                → server replies {"type":"partial","text":..}
  │
  ▼
FastAPI backend
  │
  ├─ Apple Silicon ─┐
  │                  └─► mlx-whisper large-v3-turbo   (~9× real-time, GPU)
  │
  └─ everywhere else ─► faster-whisper large-v3-turbo (CPU / CUDA)
```

The wire format is the same for every platform — the backend selection happens
once at startup, fully transparent to the frontend.

---

## ⚙️ Requirements

**All platforms** need:

- **Python 3.11** (auto-installed by `uv` if missing)
- **`uv`** — the Python package & venv manager

| Platform | Backend auto-selected | Extra OS packages needed |
|---|---|---|
| **macOS Apple Silicon (M1/M2/M3/M4)** | `mlx-whisper` (GPU) | none |
| **macOS Intel** | `faster-whisper` (CPU) | none |
| **Linux** | `faster-whisper` (CPU or CUDA) | none (CUDA optional — install yourself for GPU accel) |
| **Windows** | `faster-whisper` (CPU or CUDA) | none (CUDA optional — install yourself for GPU accel) |

> **Quick health check** — `python native/run.py device` prints which backend
> would be picked on your machine without downloading any model.

---

## 🚀 Quick start

### 1. Install `uv`

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh            # or: brew install uv

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Clone & set up

```bash
git clone https://github.com/iSkrumpie/local-transcribe.git
cd local-transcribe
python native/run.py setup        # one-time: venv + deps + first model download (~1.5–3 GB)
```

`setup` automatically:
- creates `native/.venv` with Python 3.11
- installs `fastapi`, `uvicorn`, `python-multipart`, `faster-whisper`
- on **Apple Silicon**: also installs `mlx-whisper`
- picks the right backend on first start

### 3. Start the server

```bash
python native/run.py start        # background daemon
open http://localhost:8000        # macOS; on Linux: xdg-open; Windows: start http://localhost:8000
```

Other commands:

| Command | What it does |
|---|---|
| `python native/run.py status` | Is it running? + health info |
| `python native/run.py logs` | Tail the logs (Ctrl+C to exit) |
| `python native/run.py stop` | Stop the daemon |
| `python native/run.py restart` | Reload after code changes |
| `python native/run.py foreground` | Run in foreground (Ctrl+C to stop) |
| `python native/run.py device` | Show which backend is active |

Override port: `python native/run.py start --port 9000`

> ℹ️ **macOS / Linux legacy users** — the old `native/run-native.sh` script is
> still there as a thin wrapper around `run.py` so existing muscle memory keeps
> working. Prefer `run.py` — it works on Windows too.

---

## 🖥️ Usage

| Key | Action |
|---|---|
| <kbd>Space</kbd> | Toggle Record ↔ Pause |
| <kbd>.</kbd> | Stop & finalize transcript |
| <kbd>⌘/Ctrl + C</kbd> (in textarea) | Copy transcript |
| Button bar | Same actions, mouse-friendly |

Workflow:

1. **Press <kbd>Space</kbd>** (or click Record).
2. **Speak.** The textarea fills with text in real time (partial updates every ~1.5 s).
3. **Press <kbd>Space</kbd>** again to pause (orange status). Press again to resume.
4. **Press <kbd>.</kbd>** when you're done speaking. ⚠️ The recording ends immediately — anything you say after is lost.
5. Edit anything, hit **Copy**.

---

## ⚙️ Configuration

All via environment variables — set them before `start` or `foreground`:

| Variable | Default | Notes |
|---|---|---|
| `WHISPER_BACKEND` | `auto` | `auto` picks the best backend; force `mlx` or `fw` |
| `WHISPER_MODEL` | `large-v3-turbo` | Logical name — mapped to the right HF repo per backend |
| `FW_DEVICE` | `auto` | faster-whisper only: `cpu`, `cuda`, or `auto` |
| `FW_COMPUTE_TYPE` | `auto` | faster-whisper only: `auto`, `int8`, `float16`, … |
| `PORT` | `8000` | HTTP port |

### Logical → physical model mapping

The same logical name expands to different HuggingFace repos per backend:

| Logical | MLX (Apple) | faster-whisper (cross-platform) |
|---|---|---|
| `large-v3-turbo` *(default)* | `mlx-community/whisper-large-v3-turbo` | `Systran/faster-whisper-large-v3-turbo` |
| `large-v3` | `mlx-community/whisper-large-v3-mlx` | `Systran/faster-whisper-large-v3` |
| `medium.en` | `mlx-community/whisper-medium.en-mlx` | `Systran/faster-whisper-medium.en` |
| `small` | `mlx-community/whisper-small` | `Systran/faster-whisper-small` |
| `tiny` | `mlx-community/whisper-tiny` | `Systran/faster-whisper-tiny` |

Pass a full HF repo id to override the mapping:
`WHISPER_MODEL=Systran/faster-whisper-large-v2 python native/run.py start`.

---

## 📊 Performance

| Hardware | Backend | Model | RTFx (real-time factor) |
|---|---|---|---|
| **MacBook Pro M3 Pro / 18 GB** | `mlx-whisper` (GPU) | `large-v3-turbo` | **~8.7×** |
| **MacBook Pro M3 Pro / 18 GB** | `mlx-whisper` (GPU) | `large-v3-mlx` | ~5.3× |
| Modern x86 CPU (8 cores) | `faster-whisper` (CPU int8) | `large-v3-turbo` | ~0.7× – 1.5× |
| NVIDIA RTX 3060+ | `faster-whisper` (CUDA) | `large-v3-turbo` | ~5× – 10× |

Live-streaming latency with WebSocket (1 s audio chunks): typically **1.3 s – 1.5 s**
of end-to-end delay → the textarea updates roughly every 1.5 s.

---

## 🗂️ Project layout

```
local-transcribe/
├── README.md                   ← you are here
├── LICENSE                     (MIT)
├── .gitignore
├── backend/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── app/
│       ├── __init__.py
│       ├── main.py             # FastAPI: routes + WS + static
│       ├── transcriber.py      # backend factory (auto-pick + swap)
│       ├── backends/
│       │   ├── base.py         # Protocol + TranscriptionResult
│       │   ├── mlx_backend.py  # Apple Silicon (mlx-whisper)
│       │   └── fw_backend.py   # CPU/CUDA (faster-whisper)
│       └── static/             # frontend (served by FastAPI)
│           ├── index.html
│           ├── style.css
│           ├── app.js
│           └── logo.png        # favicon + brand
├── native/
│   ├── run.py                  # ✔️ use this — cross-platform launcher
│   ├── run-native.sh           # legacy bash wrapper (Linux/macOS)
│   └── .venv/                  # auto-created by `setup`
├── logs/                       # server.log, server.pid (gitignored)
└── .github/
    └── workflows/
        └── ci.yml              # lint + smoke-test on Ubuntu/macOS/Windows
```

---

## 🧰 Troubleshooting

### "Mic permission denied"
Your browser blocked the mic. Click the camera/mic icon in the address bar, allow, refresh.

### `mlx_whisper` import fails
You need Apple Silicon. `mlx` does not run on Intel Macs or any non-M-series
system. The launcher will automatically fall back to `faster-whisper` — verify
with `python native/run.py device`.

### Server is slow
You're probably on the default `large-v3-turbo` model. Faster options:
- Apple Silicon: `WHISPER_MODEL=medium.en` (EN-only, fastest)
- CPU: `WHISPER_MODEL=tiny` (very fast, lower accuracy)
- NVIDIA GPU: install CUDA-enabled CTranslate2 (see faster-whisper docs)

### CUDA on Windows / Linux
Install the CUDA toolkit matching your driver, plus a CUDA-enabled
[`ctranslate2`](https://github.com/OpenNMT/CTranslate2) build — then
`FW_DEVICE=cuda` unlocks GPU acceleration.

### Text in the textarea duplicates
Hard-reload the page (`⌘/Ctrl + Shift + R`). The fix is already in place;
a stale cache can sneak duplicates through.

### Windows: port already in use
Find the blocker: `netstat -ano | findstr :8000`, then `taskkill /PID <pid> /F`.

### macOS / Linux: port already in use
The launcher will auto-evict with `fuser -k`. If that fails (e.g. a process
not owned by you), stop it manually or pick a different `--port`.

---

## 🤔 Why not just use OpenAI Whisper / VibeVoice?

| Candidate | Verdict |
|---|---|
| **mlx-whisper large-v3-turbo** ✅ | 8.7× RTFx on M3 Pro, MIT, near-large-v3 quality. **Default on Apple Silicon.** |
| **faster-whisper large-v3-turbo** ✅ | Cross-platform (CPU + CUDA), MIT, same family of models. **Default on Linux/Windows/Intel mac.** |
| ~~VibeVoice-ASR-7B~~ | TTS-first ICML 2026 paper. STT is 60-min batch, ~16 GB VRAM. Wrong fit. |
| ~~Parakeet TDT 0.6B v3~~ | NVIDIA GPU only. |
| ~~faster-whisper Docker CPU~~ | ~2.7× RTFx — too slow for live streaming. (Was the v0.1 build, superseded by the native mlx path.) |

---

## 📜 License

MIT — see [LICENSE](LICENSE).
`mlx-whisper` is MIT. `faster-whisper` is MIT. Whisper (OpenAI) is MIT.

---

## 🙏 Credits

Built by Timm Flagmeyer. The 1.0 cross-platform release refactors the
originally macOS-only v0.3 build around a small pluggable backend protocol.
