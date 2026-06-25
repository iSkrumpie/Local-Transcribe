"""
MLX backend — `mlx-whisper` on Apple Silicon (M1/M2/M3/M4).

`mlx` is Apple's ML framework and runs only on Apple Silicon. On Linux/Windows
or Intel Macs this backend refuses to load and `select_backend()` will fall
back to `FasterWhisperBackend`.

Models (HF repos, MLX pre-converted):
  - mlx-community/whisper-large-v3-turbo    DEFAULT (~9× RTFx, near-large-v3 quality)
  - mlx-community/whisper-large-v3-mlx      best accuracy (~5× RTFx)
  - mlx-community/whisper-medium.en-mlx     EN-only, fastest
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger(__name__)


# Logical name → MLX-format HF repo
MODEL_MAP: dict[str, str] = {
    "large-v3-turbo":   "mlx-community/whisper-large-v3-turbo",
    "large-v3":         "mlx-community/whisper-large-v3-mlx",
    "medium.en":        "mlx-community/whisper-medium.en-mlx",
    "small":            "mlx-community/whisper-small",
    "base":             "mlx-community/whisper-base",
    "tiny":             "mlx-community/whisper-tiny",
}

DEFAULT_LOGICAL = "large-v3-turbo"
DEFAULT_REPO = MODEL_MAP[DEFAULT_LOGICAL]


class MLXBackend:
    """`mlx-whisper` wrapper — Apple Silicon only."""

    name = "mlx-whisper"

    def __init__(self, model: str | None = None):
        # Lazy import: importing `mlx_whisper` will explode on non-Apple-Silicon.
        import mlx_whisper  # noqa: F401  (side-effect: ensure importable)

        self._mlx_whisper = mlx_whisper
        logical = model or "large-v3-turbo"
        self.model_name = MODEL_MAP.get(logical, logical)
        # mlx-whisper is not re-entrant safe → serialise calls
        self._lock = threading.Lock()
        log.info("MLXBackend ready (model=%s)", self.model_name)

    @property
    def device(self) -> str:
        return "mlx-gpu"

    def warmup(self) -> None:
        # mlx-whisper loads lazily on first `transcribe()` — no explicit warm-up needed
        return None

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        beam_size: int = 1,
    ) -> "TranscriptionResult":  # noqa: F821
        from .base import TranscriptionResult  # local import to avoid cycle at module load

        with self._lock:
            result: dict[str, Any] = self._mlx_whisper.transcribe(
                audio_path,
                path_or_hf_repo=self.model_name,
                language=language if language else None,
            )
            segments = [
                {
                    "start": float(s.get("start", 0.0)),
                    "end": float(s.get("end", 0.0)),
                    "text": (s.get("text") or "").strip(),
                }
                for s in result.get("segments", [])
            ]
            text = " ".join(s["text"] for s in segments).strip()
            if not text and "text" in result:
                text = result["text"].strip()

            return TranscriptionResult(
                text=text,
                language=result.get("language", language or "unknown"),
                language_probability=1.0,   # mlx-whisper doesn't expose this
                duration=float(result.get("duration", 0.0)),
                segments=segments,
            )
