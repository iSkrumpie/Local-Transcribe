"""
Transcriber — thin async-friendly wrapper around an `STTBackend`.

Auto-picks the right backend:
  - Apple Silicon (macOS arm64 + mlx_whisper importable) → MLXBackend
  - else                                       → FasterWhisperBackend

Override with `WHISPER_BACKEND=mlx|fw|auto` (default: auto).

The backend selection is wrapped in a `threading.Lock` because neither
mlx-whisper nor faster-whisper/CTranslate2 are re-entrant safe.
"""

from __future__ import annotations

import logging
import os
import platform
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backends.base import STTBackend, TranscriptionResult

log = logging.getLogger(__name__)


def _can_import_mlx() -> bool:
    """Cheap probe: is `mlx_whisper` actually usable? Returns False on any error."""
    try:
        import mlx_whisper  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def select_backend(
    prefer: str | None = None,
    model: str | None = None,
) -> "STTBackend":
    """
    Pick and instantiate the right backend.

    Args:
        prefer: 'mlx' | 'fw' | 'auto' | None (env WHISPER_BACKEND, default 'auto')
        model:  logical model name, e.g. 'large-v3-turbo'
                (falls back to env WHISPER_MODEL, default 'large-v3-turbo')
    """
    pref = (prefer or os.getenv("WHISPER_BACKEND") or "auto").lower()

    is_apple_silicon = (
        platform.system() == "Darwin" and platform.machine() == "arm64"
    )
    can_mlx = is_apple_silicon and _can_import_mlx()

    # Force a specific backend: try and fail loudly.
    if pref == "mlx":
        if not is_apple_silicon:
            raise RuntimeError(
                "WHISPER_BACKEND=mlx requested but this is not Apple-Silicon "
                "(system=%r, machine=%r). The mlx backend only runs on M-series Macs."
                % (platform.system(), platform.machine())
            )
        if not can_mlx:
            raise RuntimeError(
                "WHISPER_BACKEND=mlx requested but mlx_whisper is not importable. "
                "Install with: pip install mlx-whisper"
            )
        from .backends.mlx_backend import MLXBackend
        log.info("Backend selected: MLXBackend (forced)")
        return MLXBackend(model=model or os.getenv("WHISPER_MODEL"))

    if pref == "fw":
        from .backends.fw_backend import FasterWhisperBackend
        log.info("Backend selected: FasterWhisperBackend (forced)")
        return FasterWhisperBackend(model=model or os.getenv("WHISPER_MODEL"))

    # Auto
    if can_mlx:
        try:
            from .backends.mlx_backend import MLXBackend
            log.info("Backend selected: MLXBackend (auto)")
            return MLXBackend(model=model or os.getenv("WHISPER_MODEL"))
        except Exception as e:  # noqa: BLE001
            log.warning("MLXBackend auto-pick failed (%s) — falling back to FasterWhisperBackend", e)

    from .backends.fw_backend import FasterWhisperBackend
    log.info("Backend selected: FasterWhisperBackend (auto)")
    return FasterWhisperBackend(model=model or os.getenv("WHISPER_MODEL"))


class Transcriber:
    """Public façade. Holds the selected backend + a serialisation lock."""

    def __init__(self, backend: "STTBackend" | None = None):
        self.backend: "STTBackend" = backend or select_backend()
        self.model_name = self.backend.model_name
        self.device = self.backend.device
        self.name = self.backend.name
        # Belt-and-braces: also serialise here so a swap-in of a different
        # non-re-entrant backend later still gets a thread-safe contract.
        self._lock = threading.Lock()

    def warmup(self) -> None:
        """Load the model now (optional — backends load lazily on first transcribe())."""
        self.backend.warmup()

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        beam_size: int = 1,
    ) -> "TranscriptionResult":
        with self._lock:
            return self.backend.transcribe(
                audio_path,
                language=language,
                beam_size=beam_size,
            )
