"""Central configuration for BhashaFlix AI.

Every knob is an environment variable so the same image can run on a laptop, a
free-tier container, or a future GPU box.  Nothing here talks to the network.
"""
from __future__ import annotations

import os
import secrets
import shutil
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


class Settings:
    """Runtime settings (resolved once, at import time)."""

    # ---------------------------------------------------------------- paths --
    storage_dir: Path = Path(_env("BFLIX_STORAGE_DIR") or (PROJECT_DIR / "storage"))
    db_path: Path = Path(_env("BFLIX_DB_PATH")) if _env("BFLIX_DB_PATH") else Path(".")

    # ------------------------------------------------------------- limits ----
    max_upload_mb: int = _int("BFLIX_MAX_UPLOAD_MB", 512)
    max_duration_sec: float = _float("BFLIX_MAX_DURATION_SEC", 900.0)  # 15 min default
    min_duration_sec: float = _float("BFLIX_MIN_DURATION_SEC", 1.0)
    max_video_streams: int = 4
    max_audio_streams: int = 8
    storage_quota_mb: int = _int("BFLIX_STORAGE_QUOTA_MB", 4096)
    retention_hours: float = _float("BFLIX_RETENTION_HOURS", 24.0)
    upload_chunk_mb: int = 8
    job_timeout_sec: float = _float("BFLIX_JOB_TIMEOUT_SEC", 3600.0)

    # ------------------------------------------------------------ security ---
    api_token: str = _env("BFLIX_API_TOKEN")
    allow_open_registration: bool = _bool("BFLIX_ALLOW_ANONYMOUS_JOBS", True)
    rate_limit_per_min: int = _int("BFLIX_RATE_LIMIT_PER_MIN", 240)
    cors_origins: tuple[str, ...] = tuple(
        o for o in (_env("BFLIX_CORS_ORIGINS") or "*").split(",") if o
    )
    public_base_url: str = _env("BFLIX_PUBLIC_BASE_URL")
    trust_proxy_headers: bool = _bool("BFLIX_TRUST_PROXY", True)
    max_queue_depth: int = _int("BFLIX_MAX_QUEUE_DEPTH", 25)

    # -------------------------------------------------------------- workers --
    worker_threads: int = max(1, _int("BFLIX_WORKER_THREADS", 1))
    # GPU/CPU heavy stages are serialised by default on ₹0 hardware.

    # --------------------------------------------------------------- engines --
    asr_engine: str = _env("BFLIX_ASR_ENGINE", "auto").lower()
    asr_model: str = _env("BFLIX_ASR_MODEL", "small")
    asr_compute_type: str = _env("BFLIX_ASR_COMPUTE_TYPE", "int8")
    diarize_engine: str = _env("BFLIX_DIARIZE_ENGINE", "auto").lower()
    hf_token: str = _env("BFLIX_HF_TOKEN") or _env("HF_TOKEN")
    translate_engine: str = _env("BFLIX_TRANSLATE_ENGINE", "auto").lower()
    translate_model: str = _env("BFLIX_TRANSLATE_MODEL", "facebook/nllb-200-distilled-600M")
    libretranslate_url: str = _env("BFLIX_LIBRETRANSLATE_URL")
    llm_base_url: str = _env("BFLIX_LLM_BASE_URL")
    llm_api_key: str = _env("BFLIX_LLM_API_KEY")
    llm_model: str = _env("BFLIX_LLM_MODEL", "gpt-4o-mini")
    tts_engine: str = _env("BFLIX_TTS_ENGINE", "auto").lower()
    xtts_model: str = _env("BFLIX_XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
    piper_voices_dir: Path = Path(
        _env("BFLIX_PIPER_VOICES_DIR") or (PROJECT_DIR / "storage" / "models" / "piper")
    )
    separate_engine: str = _env("BFLIX_SEPARATE_ENGINE", "auto").lower()
    demucs_model: str = _env("BFLIX_DEMUCS_MODEL", "htdemucs")

    # --------------------------------------------------------------- audio ----
    work_sample_rate: int = 48000
    asr_sample_rate: int = 16000
    dub_sample_rate: int = 48000
    max_tempo_stretch: float = _float("BFLIX_MAX_TEMPO", 1.45)
    min_tempo_stretch: float = _float("BFLIX_MIN_TEMPO", 0.75)
    background_duck_db: float = _float("BFLIX_BACKGROUND_DUCK_DB", -1.5)
    dialogue_gain_db: float = _float("BFLIX_DIALOGUE_GAIN_DB", 0.0)

    # -------------------------------------------------------------- ffmpeg ----
    ffmpeg_bin: str = _env("BFLIX_FFMPEG") or _env("FFMPEG_BIN")
    ffprobe_bin: str = _env("BFLIX_FFPROBE") or _env("FFPROBE_BIN")

    def __init__(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if not _env("BFLIX_DB_PATH"):
            self.db_path = self.storage_dir / "bhashaflix.sqlite3"
        self.jobs_dir = self.storage_dir / "jobs"
        self.tmp_dir = self.storage_dir / "tmp"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.piper_voices_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ help --
    @property
    def auth_required(self) -> bool:
        return bool(self.api_token)

    @property
    def instance_id(self) -> str:
        """Stable-ish id used in the UI to show *which* backend is running."""
        return f"bhashaflix-{abs(hash(str(self.storage_dir))) % 100000:05d}"

    def describe(self) -> dict:
        return {
            "max_upload_mb": self.max_upload_mb,
            "max_duration_sec": self.max_duration_sec,
            "retention_hours": self.retention_hours,
            "auth_required": self.auth_required,
            "worker_threads": self.worker_threads,
            "storage_quota_mb": self.storage_quota_mb,
            "instance_id": self.instance_id,
            "public_base_url": self.public_base_url,
        }


settings = Settings()


@lru_cache(maxsize=1)
def ffmpeg_executable() -> str | None:
    """Resolve ffmpeg: explicit env var -> PATH -> imageio-ffmpeg wheel."""
    for candidate in (settings.ffmpeg_bin, shutil.which("ffmpeg")):
        if candidate and Path(candidate).exists():
            return candidate
    try:  # bundled static build (pip install imageio-ffmpeg)
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:  # pragma: no cover - optional dependency
        pass
    return None


@lru_cache(maxsize=1)
def ffprobe_executable() -> str | None:
    """Resolve ffprobe.  When absent we fall back to PyAV metadata probing."""
    for candidate in (settings.ffprobe_bin, shutil.which("ffprobe")):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def random_token() -> str:
    return secrets.token_urlsafe(24)
