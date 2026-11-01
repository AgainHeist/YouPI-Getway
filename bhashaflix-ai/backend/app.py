"""BhashaFlix AI — FastAPI application.

Run locally:
    uvicorn backend.app:app --host 0.0.0.0 --port 8000

The same process serves the static frontend and the API, which keeps the ₹0
single-service deployment simple (Render/HF Spaces/Fly/Koyeb...).  The frontend
can also be hosted separately on Cloudflare Pages — see docs/DEPLOYMENT.md.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import FRONTEND_DIR, ffmpeg_executable, ffprobe_executable, settings
from .db import init_db
from .models import error_payload
from .routes import jobs as jobs_routes
from .routes import meta as meta_routes
from .services import repo
from .workers.worker import queue_service, start_queue, stop_queue

logging.basicConfig(
    level=os.environ.get("BFLIX_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("bhashaflix")


async def retention_loop() -> None:
    """Delete expired jobs and stale previews (privacy + free-tier hygiene)."""
    while True:
        try:
            await asyncio.sleep(600)
            if settings.retention_hours > 0:
                for item in repo.expired_jobs(settings.retention_hours):
                    repo.delete_job(item["id"], hard=True)
                    log.info("retention: deleted expired job %s", item["id"])
            cutoff = time.time() - 3600
            for preview in settings.tmp_dir.glob("preview_*.wav"):
                try:
                    if preview.stat().st_mtime < cutoff:
                        preview.unlink()
                except OSError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover
            break
        except Exception:  # pragma: no cover
            log.exception("retention sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("storage=%s db=%s", settings.storage_dir, settings.db_path)
    log.info("ffmpeg=%s ffprobe=%s", ffmpeg_executable(), ffprobe_executable() or "(PyAV fallback)")
    if not ffmpeg_executable():
        log.error("FFmpeg is missing — attach BFLIX_FFMPEG or `pip install imageio-ffmpeg`.")
    start_queue()
    sweeper = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        sweeper.cancel()
        stop_queue()


app = FastAPI(
    title="BhashaFlix AI",
    version="1.0.0",
    description=(
        "Automatic movie language conversion and dubbing. The original video is never "
        "altered; only the spoken dialogue is replaced with AI-generated speech."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Disposition", "Content-Length"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    started = time.time()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "microphone=(), camera=(), geolocation=()")
    elapsed = (time.time() - started) * 1000
    if request.url.path.startswith("/api") and elapsed > 2000:
        log.info("slow request %s %s %.0fms", request.method, request.url.path, elapsed)
    return response


app.include_router(meta_routes.router)
app.include_router(jobs_routes.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        payload = detail
    else:
        payload = {"code": f"HTTP_{exc.status_code}", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": payload}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Invalid request.", "detail": exc.errors()}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": error_payload("INTERNAL_ERROR", str(exc))})


# --------------------------------------------------------------------------- #
# static frontend (optional — Cloudflare Pages can host it instead)
# --------------------------------------------------------------------------- #
if FRONTEND_DIR.exists():

    def _page(name: str) -> FileResponse | JSONResponse:
        path = FRONTEND_DIR / name
        if path.exists():
            return FileResponse(path, headers={"Cache-Control": "no-cache"})
        return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND", "message": f"{name} is missing."}})

    @app.get("/", include_in_schema=False)
    def index():
        return _page("index.html")

    @app.get("/{page}.html", include_in_schema=False)
    def html_page(page: str):
        if not all(c.isalnum() or c in "-_" for c in page):
            return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND"}})
        return _page(f"{page}.html")

    @app.get("/css/{name}", include_in_schema=False)
    def css(name: str):
        if "/" in name or ".." in name:
            return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND"}})
        return _page(f"css/{name}")

    @app.get("/js/{name}", include_in_schema=False)
    def js(name: str):
        if "/" in name or ".." in name:
            return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND"}})
        return _page(f"js/{name}")

    @app.get("/assets/{name}", include_in_schema=False)
    def assets(name: str):
        if "/" in name or ".." in name:
            return JSONResponse(status_code=404, content={"error": {"code": "NOT_FOUND"}})
        return _page(f"assets/{name}")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("BFLIX_RELOAD")),
    )
