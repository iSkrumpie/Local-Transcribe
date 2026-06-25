"""
STT backend abstraction.

A backend is a single class implementing the `STTBackend` protocol:
`transcribe(audio_path, language=None, beam_size=1) -> TranscriptionResult`.

Two concrete backends ship in this package:
- `MLXBackend` — Apple Silicon only (uses mlx-whisper)
- `FasterWhisperBackend` — CPU / CUDA (cross-platform)

Selection lives in `app.transcriber.select_backend()`.
"""
from .base import STTBackend, TranscriptionResult
from .mlx_backend import MLXBackend
from .fw_backend import FasterWhisperBackend

__all__ = [
    "STTBackend",
    "TranscriptionResult",
    "MLXBackend",
    "FasterWhisperBackend",
]
