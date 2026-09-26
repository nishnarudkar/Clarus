"""FastAPI app: browser WebSocket, REST health check, and the built frontend."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import REPO_ROOT, settings
from .ws_session import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Clarus")
app.include_router(ws_router)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "assemblyai_key_configured": bool(settings.assemblyai_api_key),
        "speech_model": settings.streaming_speech_model,
    }


@app.get("/api/config")
async def public_config() -> dict:
    """Non-secret settings the UI displays (thresholds stay defined in config.py)."""
    return {"conf_band_high": settings.conf_band_high, "conf_band_low": settings.conf_band_low}


# Serve the built frontend (frontend/dist) when present: one service, one URL.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
