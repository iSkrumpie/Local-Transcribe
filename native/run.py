#!/usr/bin/env python3
"""
Local Transcribe — cross-platform launcher.

A single launcher script for Linux / macOS / Windows.
Sub-commands (forwarded to bash-style for familiarity):

  setup       create venv + install deps (platform-aware)
  start       launch server as background daemon
  stop        stop the daemon
  restart     stop + start
  status      is it running? + /api/health
  logs        tail the logs (foreground, Ctrl+C to stop)
  foreground  run in foreground (Ctrl+C to stop)
  device      print the resolved backend (mlx vs. faster-whisper) without running it

Auto-picks the backend:
  macOS arm64 with mlx-whisper installed → mlx-whisper (Apple Silicon GPU)
  everything else                         → faster-whisper (CPU / CUDA)

Override via env:
  WHISPER_BACKEND=mlx|fw|auto        default: auto
  WHISPER_MODEL=large-v3-turbo|...   default: large-v3-turbo
  FW_DEVICE=cpu|cuda|auto            default: auto
  PORT=8000                          default: 8000
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
VENV = Path(__file__).resolve().parent / ".venv"
LOGS = ROOT / "logs"
PIDFILE = LOGS / "server.pid"
LOGFILE = LOGS / "server.log"
DEFAULT_PORT = 8000

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"


# ---------- helpers ---------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def err(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr, flush=True)


def ok(msg: str) -> None:
    print(f"✅ {msg}", flush=True)


def info(msg: str) -> None:
    print(f"→ {msg}", flush=True)


def venv_python() -> Path:
    if IS_WINDOWS:
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def venv_uvicorn() -> Path:
    if IS_WINDOWS:
        return VENV / "Scripts" / "uvicorn.exe"
    return VENV / "bin" / "uvicorn"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False


def pid_alive(pid: int) -> bool:
    try:
        if IS_WINDOWS:
            # tasklist /FI "PID eq <pid>" — keep it simple, fall back to platform calls
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def read_pid() -> Optional[int]:
    if not PIDFILE.exists():
        return None
    try:
        return int(PIDFILE.read_text().strip())
    except (ValueError, OSError):
        return None


def wait_for_ready(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionResetError, OSError):
            time.sleep(0.4)
    return False


def curl_health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2.0) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


def ensure_uv() -> None:
    if shutil.which("uv"):
        return
    err("`uv` is not on your PATH. Install it: https://docs.astral.sh/uv/getting-started/installation/")
    if IS_WINDOWS:
        err("  Windows:  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
    elif IS_MAC:
        err("  macOS:    brew install uv  ||  curl -LsSf https://astral.sh/uv/install.sh | sh")
    else:
        err("  Linux:    curl -LsSf https://astral.sh/uv/install.sh | sh")
    sys.exit(2)


def ensure_python_311() -> None:
    # uv will download a 3.11 interpreter on demand if missing.
    # We just emit an info line — uv handles the rest.
    info("Using Python 3.11 (pulled automatically by uv if not installed)")


# ---------- commands --------------------------------------------------------

def cmd_setup() -> int:
    ensure_uv()
    LOGS.mkdir(parents=True, exist_ok=True)
    if not VENV.exists():
        info(f"Creating venv at {VENV}")
        subprocess.check_call(["uv", "venv", "--python", "3.11", str(VENV)])
    else:
        info(f"Reusing existing venv at {VENV}")

    # Activate via env vars rather than `source activate` so this works on
    # Windows (where activate.bat is fragile in subprocesses).
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV)
    vpy = str(venv_python())

    info("Installing core backend deps (fastapi, uvicorn, python-multipart, faster-whisper) …")
    subprocess.check_call(
        ["uv", "pip", "install", "--python", vpy,
         "fastapi", "uvicorn[standard]", "python-multipart", "faster-whisper"],
        env=env,
    )

    backend_hint = "faster-whisper (cross-platform)"
    if IS_APPLE_SILICON:
        info("Detected Apple Silicon (macOS arm64) — installing mlx-whisper too …")
        try:
            subprocess.check_call(
                ["uv", "pip", "install", "--python", vpy, "mlx-whisper"],
                env=env,
            )
            backend_hint = "mlx-whisper (Apple Silicon GPU) — faster-whisper will be used as fallback"
        except subprocess.CalledProcessError:
            warn = "⚠️  mlx-whisper install failed (this is fine on non-Apple-Silicon)"
            print(warn, flush=True)

    print()
    ok(f"Setup complete. Backend: {backend_hint}.")
    info("Start with: python native/run.py start")
    return 0


def cmd_start(port: int) -> int:
    pid = read_pid()
    if pid and pid_alive(pid):
        ok(f"Already running (PID {pid}). Use 'restart' to reload.")
        return 0

    if not VENV.exists():
        info("No venv found — running setup first …")
        cmd_setup()

    if not IS_WINDOWS and port_in_use(port):
        info(f"Port {port} is busy — trying to evict the old process …")
        try:
            subprocess.check_call(["fuser", "-k", f"{port}/tcp"], stderr=subprocess.DEVNULL)
            time.sleep(0.8)
        except (subprocess.CalledProcessError, FileNotFoundError):
            err(f"Port {port} is busy but I couldn't free it. Stop the conflicting process manually.")
            return 1
    elif IS_WINDOWS and port_in_use(port):
        err(f"Port {port} is busy. Stop the conflicting process (e.g. `netstat -ano | findstr :{port}`, then `taskkill /PID <pid> /F`).")
        return 1

    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV)
    env["PORT"] = str(port)

    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOGFILE, "ab", buffering=0)

    cwd = str(BACKEND)
    cmd = [
        str(venv_uvicorn()), "app.main:app",
        "--host", "0.0.0.0", "--port", str(port), "--workers", "1",
    ]

    if IS_WINDOWS:
        # Background-as-detached-process via CREATE_NEW_PROCESS_GROUP + CREATE_NO_WINDOW.
        # The window-less flag hides the cmd window that would otherwise flash up.
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=log_handle, stderr=log_handle,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    else:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=log_handle, stderr=log_handle,
            start_new_session=True,   # nohup-equivalent: ignore SIGHUP, own process group
            close_fds=True,
        )

    PIDFILE.write_text(str(proc.pid))
    info(f"Started Local Transcribe on http://localhost:{port} (PID {proc.pid})")
    info(f"logs: {LOGFILE}")

    if wait_for_ready(port):
        ok(f"Ready (PID {proc.pid})")
        h = curl_health(port)
        if h:
            print(json.dumps(h, indent=2))
    else:
        err(f"Server didn't become ready in 15s. Try: python native/run.py logs")
        return 1
    return 0


def cmd_stop() -> int:
    pid = read_pid()
    if not pid or not pid_alive(pid):
        info("Not running.")
        try:
            PIDFILE.unlink(missing_ok=True)
        except TypeError:  # py<3.8
            try: PIDFILE.unlink()
            except FileNotFoundError: pass
        return 0

    info(f"Stopping PID {pid} …")
    try:
        if IS_WINDOWS:
            subprocess.check_call(["taskkill", "/PID", str(pid), "/F"])
        else:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 3s for graceful shutdown
            for _ in range(10):
                time.sleep(0.3)
                if not pid_alive(pid):
                    break
            if pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError) as e:
        err(f"Failed to stop PID {pid}: {e}")
    try:
        PIDFILE.unlink()
    except FileNotFoundError:
        pass
    ok("Stopped.")
    return 0


def cmd_restart(port: int) -> int:
    cmd_stop()
    time.sleep(0.5)
    return cmd_start(port)


def cmd_status(port: int) -> int:
    pid = read_pid()
    if not pid or not pid_alive(pid):
        err("Not running.")
        return 1
    h = curl_health(port)
    if h:
        ok(f"Running (PID {pid}) on http://localhost:{port}")
        print(json.dumps(h, indent=2))
        return 0
    err(f"Running (PID {pid}) but /api/health not responsive.")
    return 1


def cmd_logs() -> int:
    if not LOGFILE.exists():
        err(f"No log file yet at {LOGFILE}")
        return 1
    # Universal tail: poll the file, print new lines, Ctrl+C to exit.
    info(f"Tailing {LOGFILE} — Ctrl+C to stop")
    pos = 0
    try:
        with open(LOGFILE, "r", encoding="utf-8", errors="replace") as f:
            # Show existing content first
            for line in f:
                print(line, end="")
            pos = f.tell()
        while True:
            time.sleep(0.3)
            with open(LOGFILE, "r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                if chunk:
                    print(chunk, end="")
                    pos = f.tell()
    except KeyboardInterrupt:
        print()
        return 0


def cmd_foreground(port: int) -> int:
    if not VENV.exists():
        info("No venv found — running setup first …")
        cmd_setup()
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV)
    env["PORT"] = str(port)
    cmd = [
        str(venv_uvicorn()), "app.main:app",
        "--host", "0.0.0.0", "--port", str(port),
    ]
    info(f"Running in foreground on http://localhost:{port} — Ctrl+C to stop")
    try:
        return subprocess.call(cmd, cwd=str(BACKEND), env=env)
    except KeyboardInterrupt:
        return 0


def cmd_device() -> int:
    """Show which backend the server will pick, without loading the model."""
    info(f"System: {platform.system()} / machine: {platform.machine()}")
    info(f"Apple Silicon: {IS_APPLE_SILICON}")
    # Probe venv mlx_whisper without full model load
    if not VENV.exists():
        err("No venv found. Run setup first.")
        return 1
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV)
    code = (
        "import platform, os, sys\n"
        "sys.path.insert(0, '.')\n"
        "os.chdir(r'" + str(BACKEND).replace("\\", "\\\\") + "')\n"
        "from app.transcriber import select_backend\n"
        "b = select_backend()\n"
        f"print('backend=' + b.name)\n"
        f"print('model=' + b.model_name)\n"
        f"print('device=' + b.device)\n"
    )
    return subprocess.call([str(venv_python()), "-c", code], env=env, cwd=str(BACKEND))


# ---------- arg parser ------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Local Transcribe — cross-platform launcher "
                    "(Linux / macOS / Windows).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=["setup", "start", "stop", "restart", "status", "logs", "foreground", "device"],
        help="Launcher sub-command.",
    )
    parser.add_argument(
        "--port", "-p", type=int, default=int(os.getenv("PORT", DEFAULT_PORT)),
        help=f"Listening port (default: {DEFAULT_PORT}).",
    )
    args = parser.parse_args(argv)

    cmd = args.command
    port = args.port

    LOGS.mkdir(parents=True, exist_ok=True)

    if cmd == "setup":
        return cmd_setup()
    if cmd == "start":
        return cmd_start(port)
    if cmd == "stop":
        return cmd_stop()
    if cmd == "restart":
        return cmd_restart(port)
    if cmd == "status":
        return cmd_status(port)
    if cmd == "logs":
        return cmd_logs()
    if cmd == "foreground":
        return cmd_foreground(port)
    if cmd == "device":
        return cmd_device()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
