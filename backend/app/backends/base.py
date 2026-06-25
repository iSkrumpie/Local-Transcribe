"""
STT backend protocol + shared result type.

A backend exposes a single method — `transcribe(audio_path, language, beam_size)`
— that returns a `TranscriptionResult`. The rest of the application (FastAPI
routes, WebSocket protocol, frontend) is decoupled from the choice of model
runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    duration: float
    segments: list[dict] = field(default_factory=list)


class STTBackend(Protocol):
    """Common interface for all STT backends."""

    name: str                         # human-readable backend id (e.g. "mlx-whisper")
    device: str                       # device string for /api/health (e.g. "mlx-gpu", "cpu")
    model_name: str                   # resolved HF repo / model id

    def warmup(self) -> None:
        """Optional: load the model into memory. Default = no-op."""
        ...

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        beam_size: int = 1,
    ) -> TranscriptionResult:
        """Transcribe an audio file and return a `TranscriptionResult`."""
        ...
