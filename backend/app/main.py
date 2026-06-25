"""
Local Transcribe — FastAPI backend.

Cross-platform STT web app:
  - macOS Apple Silicon → mlx-whisper (GPU)
  - Linux / Windows / Intel mac → faster-whisper (CPU or CUDA)

Routes:
  GET  /api/health        → status + model + backend + device info
  POST /api/transcribe    → upload a complete audio file → final transcript
  WS   /ws/transcribe     → streaming: browser sends complete WebM blobs
                            every ~1.5s; server returns partials immediately.
                            "stop" text-frame → closes cleanly with final text.
  GET  /                  → static frontend (index.html)
  GET  /favicon.ico       → logo.png (image/png)
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .transcriber import Transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("local_transcribe")

STATIC_DIR = Path(__file__).parent / "static"
transcriber: Transcriber | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcriber
    log.info("Starting Local Transcribe …")
    transcriber = await asyncio.to_thread(Transcriber)
    log.info(
        "Backend: %s | model: %s | device: %s",
        transcriber.name, transcriber.model_name, transcriber.device,
    )
    log.info("Ready to transcribe")
    yield
    log.info("Shutting down")


app = FastAPI(title="Local Transcribe", version="1.0.0", lifespan=lifespan)


# ----- API --------------------------------------------------------------------

@app.get("/api/health")
async def health():
    if transcriber is None:
        return {"status": "loading", "backend": None, "model": None, "device": None}
    return {
        "status": "ok",
        "backend": transcriber.name,
        "model": transcriber.model_name,
        "device": transcriber.device,
    }


@app.post("/api/transcribe")
async def transcribe_file(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
):
    """Upload a complete audio file, return the full transcript."""
    if transcriber is None:
        raise HTTPException(503, "Model not loaded yet")

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    # Windows: `delete=True` blocks re-open → use delete=False and clean up manually.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        log.info(
            "POST /api/transcribe: %s (%.1f KB, lang=%s)",
            file.filename, len(contents) / 1024, language,
        )
        result = await asyncio.to_thread(
            transcriber.transcribe,
            tmp_path,
            language=language if language else None,
        )
        return {
            "text": result.text,
            "language": result.language,
            "language_probability": result.language_probability,
            "duration": result.duration,
            "segments": result.segments,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.websocket("/ws/transcribe")
async def ws_transcribe(ws: WebSocket):
    await ws.accept()
    if transcriber is None:
        await ws.send_json({"type": "error", "message": "Model not loaded yet"})
        await ws.close()
        return

    language = ws.query_params.get("language") or None
    chunk_idx = 0
    last_text = ""

    try:
        while True:
            msg = await ws.receive()

            # Stop signal
            if "text" in msg and msg["text"] == "stop":
                log.info("WS: stop received after %d chunks", chunk_idx)
                await ws.send_json({"type": "stopped", "chunks": chunk_idx, "text": last_text})
                break

            # Audio blob
            if "bytes" in msg and msg["bytes"]:
                blob = msg["bytes"]
                if len(blob) < 500:
                    continue   # too small — skip silently
                chunk_idx += 1
                with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                    tmp.write(blob)
                    tmp_path = tmp.name
                try:
                    result = await asyncio.to_thread(
                        transcriber.transcribe,
                        tmp_path,
                        language=language,
                    )
                    last_text = result.text
                    log.info(
                        "WS chunk %d: %.1f KB → %d chars (lang=%s, lp=%.2f)",
                        chunk_idx, len(blob) / 1024, len(result.text),
                        result.language, result.language_probability,
                    )
                    await ws.send_json({
                        "type": "partial",
                        "text": result.text,
                        "language": result.language,
                        "language_probability": result.language_probability,
                        "duration": result.duration,
                    })
                except Exception as e:  # noqa: BLE001
                    log.exception("WS chunk failed")
                    await ws.send_json({"type": "error", "message": str(e)})
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    except WebSocketDisconnect:
        log.info("WS: client disconnected after %d chunks", chunk_idx)


# ----- Static frontend --------------------------------------------------------

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    logo = STATIC_DIR / "logo.png"
    if logo.exists():
        return FileResponse(logo, media_type="image/png")
    return Response(status_code=204)


if STATIC_DIR.exists():
    # Disable caching for the static frontend so JS/HTML updates are picked
    # up on the next page reload.
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class NoCacheStaticMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/static") or request.url.path == "/":
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

    app.add_middleware(NoCacheStaticMiddleware)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")
else:
    log.warning("Static directory %s not found — frontend will not be served", STATIC_DIR)
