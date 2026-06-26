# Local Transcribe

![Screenshot](assets/screenshots/screenshot.png)

Local-first, browser-based push-to-talk speech-to-text — runs on **Linux, macOS, and Windows**.
Press <kbd>Space</kbd> → speak → text grows in the textarea → press <kbd>.</kbd> to finalize.

No cloud, no API keys, no telemetry. Auto-picks the best local STT engine for your machine: `mlx-whisper` on Apple Silicon (GPU), `faster-whisper` everywhere else (CPU or CUDA).

---

## Features

- **Push-to-talk** — <kbd>Space</kbd> to record/pause, <kbd>.</kbd> to stop & finalize
- **Live transcription** — text grows in real time as you speak (~1.5 s updates)
- **Multilingual** — auto-detects English, German, and 97 other languages
- **Cross-platform** — one codebase, Linux / macOS / Windows
- **Auto backend** — Apple Silicon → GPU; everything else → CPU or CUDA
- **Fully local** — no network calls once the model is downloaded

---

## Quick Start

```shell
# 1. Install uv (one-time)
#    macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
#    Windows (PS):   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clone & set up
git clone https://github.com/iSkrumpie/Local-Transcribe.git
cd Local-Transcribe
python3 native/run.py setup     # Windows: python native\run.py setup

# 3. Start & open
python3 native/run.py start     # background daemon
open http://localhost:8000      # macOS · Linux: xdg-open · Windows: start http://localhost:8000
```

| Launcher command | What it does |
|---|---|
| `python3 native/run.py status` | Is it running? + `/api/health` |
| `python3 native/run.py logs` | Tail logs (Ctrl+C to exit) |
| `python3 native/run.py stop` | Stop the daemon |
| `python3 native/run.py restart` | Reload after code changes |
| `python3 native/run.py device` | Show selected backend without downloading the model |

---

## Platform Setup

### 🪟 Windows 10 / 11

```powershell
# 1. Git (if not installed)
winget install --id Git.Git        # or: https://git-scm.com/download/win

# 2. Clone + run setup (uv auto-installed if you skipped earlier)
git clone https://github.com/iSkrumpie/Local-Transcribe.git
cd Local-Transcribe
python native\run.py setup

# 3. Start server
python native\run.py start
start http://localhost:8000
```

- `'python' is not recognized` → reinstall Python and tick **Add to PATH**
- `ExecutionPolicy` blocks `install.ps1` → use `-ExecutionPolicy ByPass`
- Port 8000 busy → `netstat -ano | findstr :8000` → `taskkill /PID <pid> /F`

### 🐧 Linux (Ubuntu, Debian, Fedora, Arch)

```bash
# 1. System packages
sudo apt install -y git build-essential python3.11 python3.11-venv   # Debian / Ubuntu
# sudo dnf install -y git gcc make python3.11                          # Fedora
# sudo pacman -S git base-devel python311                              # Arch

# 2. uv (Python + venv manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc                                                       # or .zshrc / fish config

# 3. Clone + run setup
git clone https://github.com/iSkrumpie/Local-Transcribe.git
cd Local-Transcribe
python3 native/run.py setup

# 4. Start server
python3 native/run.py start
xdg-open http://localhost:8000
```

- `python: command not found` → use `python3` instead
- Mic doesn't work on Wayland → grant the browser explicit mic access via `pavucontrol` or `wpctl`
- Port 8000 busy → `sudo fuser -k 8000/tcp`

### ⚡ NVIDIA GPU (optional, both platforms)

1. Install [CUDA Toolkit 12.x](https://developer.nvidia.com/cuda-toolkit-archive) + matching cuDNN.
2. In the venv: `uv pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
3. Set `FW_DEVICE=cuda`, then restart: `python3 native/run.py restart`
4. Verify with `python3 native/run.py status` — `device` should now report `cuda`.

### 🐚 WSL (Windows Subsystem for Linux)

The Linux instructions work in WSL**2**. Mic passthrough to WSL is fragile — if you're on Windows, use the **Windows-native** install above instead.

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `WHISPER_BACKEND` | `auto` | `mlx` \| `fw` \| `auto` (auto-picks Apple-Silicon vs cross-platform) |
| `WHISPER_MODEL` | `large-v3-turbo` | Logical name → mapped to the right HF repo per backend |
| `FW_DEVICE` | `auto` | `faster-whisper` only: `cpu` \| `cuda` \| `auto` |
| `FW_COMPUTE_TYPE` | `auto` | `faster-whisper` only |
| `PORT` | `8000` | HTTP port |

The logical model name expands to different HF repos on each backend — e.g. `large-v3-turbo` → `mlx-community/whisper-large-v3-turbo` on Apple Silicon or `Systran/faster-whisper-large-v3-turbo` everywhere else. Pass a full HF repo id to override.

---

## Performance

| Hardware | Backend | RTFx |
|---|---|---|
| MacBook Pro M3 Pro | mlx-whisper GPU | **~8.7×** (`large-v3-turbo`) |
| Modern x86 CPU (8 cores) | faster-whisper int8 | ~0.7–1.5× |
| NVIDIA RTX 3060+ | faster-whisper CUDA | ~5–10× |

End-to-end live-streaming latency: ~1.3–1.5 s on Apple Silicon; longer on CPU.

---

## Troubleshooting

- **`mlx_whisper` import fails** → you need Apple Silicon. The launcher automatically falls back to `faster-whisper`; verify with `python3 native/run.py device`.
- **CUDA on Linux / Windows** → install CUDA Toolkit + cuDNN matching your driver, then `FW_DEVICE=cuda`.
- **Mic permission denied** → click the mic icon in the browser address bar → Allow → reload.
- **Server is slow** → try `WHISPER_MODEL=tiny` (fast, lower accuracy) or `WHISPER_MODEL=medium.en` on Apple Silicon.
- **Text duplicates in textarea** → hard-reload (Ctrl/⌘ + Shift + R).

---

## Contributing

Issues and pull requests are welcome. For larger changes, open an issue first. The project uses [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

## License

[MIT](LICENSE) — Copyright (c) 2026 Skrumpie
