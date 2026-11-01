"""Public metadata endpoints: languages, capabilities, health, config."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import ffmpeg_executable, ffprobe_executable, settings
from ..engines.asr import gpu_available
from ..services import languages as lang_mod
from ..services.pipeline import capabilities
from ..workers.worker import queue_service

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "instance": settings.instance_id,
        "ffmpeg": ffmpeg_executable(),
        "ffprobe": ffprobe_executable(),
        "gpu": gpu_available(),
        "queue": queue_service.stats(),
    }


@router.get("/config")
def config():
    """Everything the frontend is allowed to know.  No secrets, ever."""
    return {
        **settings.describe(),
        "default_target": "hi",
        "supported_upload_ext": [".mp4", ".mkv", ".mov", ".m4v", ".webm"],
        "stages": [
            "uploading", "extracting_audio", "transcribing", "identifying_speakers",
            "translating", "generating_voices", "synchronizing_audio", "rendering", "completed",
        ],
        "honesty_notes": [
            "Nothing here is simulated: if a model is missing the job fails with a clear error.",
            "Free hosting gives no unlimited GPU. A 15-minute limit is the default per job.",
            "The uploaded file is never modified; the rendered video copies the original video stream bit-for-bit.",
        ],
    }


@router.get("/languages")
def languages():
    return {
        "languages": lang_mod.LANGUAGES,
        "targets": [lang["code"] for lang in lang_mod.target_languages()],
        "sources": [lang["code"] for lang in lang_mod.source_languages()],
        "note": "Bhojpuri is offered for translation/voices only where the installed models support it.",
    }


@router.get("/capabilities")
def caps():
    payload = capabilities()
    payload["queue"] = queue_service.stats()
    payload["gpu"] = gpu_available()
    payload["ffmpeg"] = bool(ffmpeg_executable())
    return payload
