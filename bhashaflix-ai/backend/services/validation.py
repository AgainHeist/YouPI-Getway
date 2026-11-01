"""Upload validation: extension, magic bytes, size, probe, duration, audio."""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..engines.media import MediaError, MediaInfo, probe
from ..models import error_payload

ALLOWED_EXTENSIONS = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mkv": "matroska",
    ".mov": "quicktime",
    ".webm": "webm",
}

# ISO-BMFF (mp4/mov/m4v) starts with a box; 'ftyp' sits at offset 4.
# Matroska/WebM start with EBML magic 1A 45 DF A3.
MAGIC = {
    "isobmff": [(4, b"ftyp"), (4, b"moov"), (4, b"mdat"), (4, b"free"), (4, b"wide"), (4, b"skip")],
    "ebml": [(0, b"\x1a\x45\xdf\xa3")],
}

FORMAT_FAMILY = {
    "mp4": "isobmff",
    "m4v": "isobmff",
    "mov": "isobmff",
    "mkv": "ebml",
    "webm": "ebml",
}


class ValidationFailed(Exception):
    def __init__(self, code: str, detail: str | None = None, hint: str | None = None, status: int = 400):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.hint = hint
        self.status = status

    def payload(self) -> dict:
        return error_payload(self.code, self.detail, self.hint)


def check_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationFailed(
            "UNSUPPORTED_FORMAT",
            detail=f"'{ext or 'no extension'}' is not accepted. Allowed: MP4, MKV, MOV (also M4V, WEBM).",
            hint="Re-mux or export your movie as MP4 (H.264/AAC) for the smoothest experience.",
        )
    return ext


def check_size(size_bytes: int) -> None:
    limit = settings.max_upload_mb * 1024 * 1024
    if size_bytes > limit:
        raise ValidationFailed(
            "FILE_TOO_LARGE",
            detail=f"{size_bytes / 1048576:.1f} MB exceeds the {settings.max_upload_mb} MB limit.",
            hint="Trim the clip (30–60 s is ideal) or raise BFLIX_MAX_UPLOAD_MB on your own server.",
            status=413,
        )


def check_magic(path: Path, ext: str) -> None:
    """Cheap sniffing before we spend time on a full probe."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
    except OSError as exc:
        raise ValidationFailed("CORRUPT_MEDIA", detail=str(exc), status=400) from exc
    if len(head) < 12:
        raise ValidationFailed("CORRUPT_MEDIA", detail="File is too small to be a valid video.")
    family = FORMAT_FAMILY.get(ext.lstrip("."))
    if family and family in MAGIC:
        if not any(head[offset:offset + len(sig)] == sig for offset, sig in MAGIC[family]):
            raise ValidationFailed(
                "CORRUPT_MEDIA",
                detail="The file contents do not match the file extension.",
                hint="The upload may be incomplete or renamed. Try exporting the file again.",
            )


def check_media(info: MediaInfo) -> None:
    if not info.video_streams:
        raise ValidationFailed("CORRUPT_MEDIA", detail="No video stream found in the file.")
    if not info.audio_streams:
        raise ValidationFailed(
            "NO_AUDIO_STREAM",
            detail="The file has no audio track.",
            hint="BhashaFlix dubs spoken dialogue; a silent video has nothing to translate.",
        )
    if info.duration < settings.min_duration_sec:
        raise ValidationFailed(
            "DURATION_TOO_SHORT",
            detail=f"Duration {info.duration:.1f}s is below the {settings.min_duration_sec:.0f}s minimum.",
        )
    if info.duration > settings.max_duration_sec:
        raise ValidationFailed(
            "DURATION_TOO_LONG",
            detail=(
                f"Duration {info.duration/60:.1f} min exceeds this server's "
                f"{settings.max_duration_sec/60:.1f} min per-job limit."
            ),
            hint="Start with a 30–60 second clip. Long movies need a GPU worker (see docs/DEPLOYMENT.md).",
            status=400,
        )
    if len(info.video_streams) > settings.max_video_streams:
        raise ValidationFailed("CORRUPT_MEDIA", detail="Too many video streams in one file.")


def validate_upload(path: Path, filename: str, declared_size: int | None = None) -> dict:
    """Full validation pipeline.  Returns {'ext', 'media'} or raises ValidationFailed."""
    ext = check_extension(filename)
    size = path.stat().st_size
    check_size(size)
    if declared_size and abs(declared_size - size) > 0:
        # clients may send the browser-reported size; size on disk is authoritative
        pass
    check_magic(path, ext)
    try:
        info = probe(path)
    except MediaError as exc:
        raise ValidationFailed(exc.code or "CORRUPT_MEDIA", detail=str(exc), hint=exc.hint) from exc
    check_media(info)
    return {"ext": ext, "media": info.to_dict()}


def validate_clip_reference(info: MediaInfo) -> list[str]:
    """Non-fatal advisories shown in the UI before processing."""
    notes: list[str] = []
    video = info.video_streams[0]
    if video.codec not in {"h264", "hevc", "vp9", "av1", "mpeg4"}:
        notes.append(f"Video codec '{video.codec}' will be copied unchanged; your browser may not play it.")
    if video.height and video.height > 2160:
        notes.append("Very high resolution clip: processing will be slow on free CPU hardware.")
    audio = info.audio_streams[0]
    if audio.channels == 1:
        notes.append(
            "Mono audio detected: dialogue and music share one channel, so background preservation "
            "is limited (the original mix is kept at lower volume instead of true separation)."
        )
    if len(info.audio_streams) > 1:
        notes.append(f"{len(info.audio_streams)} audio tracks found; the first is used for dialogue.")
    if audio.codec not in {"aac", "mp3", "opus", "vorbis", "ac3", "eac3", "flac", "alac", "pcm_s16le"}:
        notes.append(f"Audio codec '{audio.codec}' will be converted to PCM for processing.")
    return notes
