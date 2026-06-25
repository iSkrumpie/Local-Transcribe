#!/usr/bin/env bash
# Local Transcribe — legacy bash launcher (Linux / macOS only).
#
# DEPRECATED: prefer `python native/run.py` — that's the cross-platform launcher
# and works identically on Linux, macOS, and Windows.
#
# This script exists so existing muscle memory keeps working. It simply
# forwards the sub-command and "--port" argument to the Python launcher.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

cmd="${1:-start}"
shift || true

PORT_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port|-p)
      PORT_ARGS+=(--port "$2"); shift 2;;
    --port=*)
      PORT_ARGS+=(--port "${1#*=}"); shift;;
    -h|--help)
      echo "Usage: $0 [setup|start|stop|restart|status|logs|foreground|device] [--port N]"; exit 0;;
    *)
      echo "❌ Unknown arg: $1" >&2; exit 2;;
  esac
done

exec python3 "$ROOT/native/run.py" "$cmd" "${PORT_ARGS[@]}"
