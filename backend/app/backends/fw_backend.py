"""
Faster-Whisper backend — `faster-whisper` / CTranslate2.

Cross-platform (Linux, macOS, Windows), supports CPU and NVIDIA CUDA.
CTranslate2 picks the best device automatically (`cpu` or `cuda`) when
`device="auto"`. Override via `FW_DEVICE` env var or constructor arg.

Models (CTranslate2-format HF repos):
  - Systran/faster-whisper-large-v3-turbo      DEFAULT (~RTF ≈ 1/2-1/3 of audio length on CPU)
  - Systran/faster-whisper-large-v3
  - Systran/faster-whisper-medium.en
  - Systran/faster-whisper-small.en
  - Systran/faster-whisper-base.en
  - Systran/faster-whisper-tiny.en
"""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)


# Logical name → CTranslate2-format HF repo
MODEL_MAP: dict[str, str] = {
    "large-v3-turbo":   "Systran/faster-whisper-large-v3-turbo",
    "large-v3":         "Systran/faster-whisper-large-v3",
    "medium":           "Systran/faster-whisper-medium",
    "medium.en":        "Systran/faster-whisper-medium.en",
    "small":            "Systran/faster-whisper-small",
    "small.en":         "Systran/faster-whisper-small.en",
    "base":             "Systran/faster-whisper-base",
    "base.en":          "Systran/faster-whisper-base.en",
    "tiny":             "Systran/faster-whisper-tiny",
    "tiny.en":          "Systran/faster-whisper-tiny.en",
}

DEFAULT_LOGICAL = "large-v3-turbo"
DEFAULT_REPO = MODEL_MAP[DEFAULT_LOGICAL]


class FasterWhisperBackend:
    """`faster-whisper` (CTranslate2) wrapper — cross-platform."""

    name = "faster-whisper"

    def __init__(
        self,
        model: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        # Lazy import — keeps import errors local to backend selection
        from faster_whisper import WhisperModel  # noqa: F401

        logical = model or "large-v3-turbo"
        self.model_name = MODEL_MAP.get(logical, logical)
        # Resolve device & compute type
        self._device = device or os.getenv("FW_DEVICE", "auto")
        self._compute_type = compute_type or os.getenv("FW_COMPUTE_TYPE", "auto")
        self._model: "WhisperModel | None" = None  # loaded on first transcribe()
        # faster-whisper CTranslate2 context is not re-entrant safe
        self._lock = threading.Lock()
        log.info(
            "FasterWhisperBackend ready (model=%s, device=%s, compute_type=%s)",
            self.model_name, self._device, self._compute_type,
        )

    @property
    def device(self) -> str:
        if self._device == "auto":
            try:
                if self._model is not None:
                    return getattr(self._model, "device", "cpu")
            except Exception:  # noqa: BLE001
                pass
            return "cpu"
        return self._device

    def _ensure_loaded(self) -> None:
        """Lazy-load on first call."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        log.info("Loading model %s on device=%s (compute_type=%s) …",
                 self.model_name, self._device, self._compute_type)
        self._model = WhisperModel(
            self.model_name,
            device=self._device,
            compute_type=self._compute_type,
        )
        log.info("Model loaded")

    def warmup(self) -> None:
        self._ensure_loaded()

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        beam_size: int = 1,
    ) -> "TranscriptionResult":  # noqa: F821
        from .base import TranscriptionResult  # local import to avoid cycle

        with self._lock:
            self._ensure_loaded()
            segments_iter, info = self._model.transcribe(  # type: ignore[union-attr]
                audio_path,
                language=language if language else None,
                beam_size=beam_size,
                vad_filter=True,            # skip silence — saves time & false triggers
            )
            segments: list[dict] = []
            text_parts: list[str] = []
            for s in segments_iter:
                seg_text = (s.text or "").strip()
                if not seg_text:
                    continue
                text_parts.append(seg_text)
                segments.append({
                    "start": float(s.start),
                    "end": float(s.end),
                    "text": seg_text,
                })
            text = " ".join(text_parts).strip()

            return TranscriptionResult(
                text=text,
                language=info.language or (language or "unknown"),
                language_probability=float(info.language_probability or 0.0),
                duration=float(info.duration or 0.0),
                segments=segments,
            )
