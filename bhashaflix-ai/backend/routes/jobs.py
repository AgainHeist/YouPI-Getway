"""Job lifecycle API: the ten endpoints from the spec plus the studio helpers."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..engines.media import probe
from ..engines.tts import TTSError, preview, voice_catalog
from ..models import STAGE_LABELS, STAGE_ORDER, error_payload
from ..security import client_ip, ensure_job, limiter, require_token
from ..services import languages as lang_mod
from ..services import pipeline, repo
from ..services.streaming import range_response
from ..services.validation import ValidationFailed, check_extension, validate_clip_reference, validate_upload
from ..workers.worker import queue_service

log = logging.getLogger("bhashaflix.api.jobs")
router = APIRouter(prefix="/api", tags=["jobs"], dependencies=[Depends(require_token)])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _rate_limit(request: Request) -> None:
    if not limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail=error_payload("RATE_LIMITED"))


async def _save_upload(upload: UploadFile, dest: Path, *, limit_mb: int) -> int:
    """Stream an upload to disk with a hard byte cap (never trust headers)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit = limit_mb * 1024 * 1024
    written = 0
    with open(dest, "wb") as fh:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > limit:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=error_payload(
                        "FILE_TOO_LARGE",
                        f"Upload exceeded the {limit_mb} MB limit.",
                        "Trim the clip or raise BFLIX_MAX_UPLOAD_MB on your own server.",
                    ),
                )
            fh.write(chunk)
    return written


def _safe_filename(name: str) -> str:
    keep = "".join(c for c in Path(name or "movie.mp4").name if c.isalnum() or c in ".-_ ()")
    return (keep or "movie.mp4")[:120]


def job_payload(job: dict) -> dict:
    """The shape the frontend consumes for status screens."""
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "stage_label": job["stage_label"],
        "stage_index": job["stage_index"],
        "stage_total": job["stage_total"],
        "stages_done": job["stages_done"],
        "progress": job["progress"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "source_name": job["source_name"],
        "source_ext": job["source_ext"],
        "source_bytes": job["source_bytes"],
        "source_lang": job["source_lang"],
        "target_lang": job["target_lang"],
        "input_mode": job["input_mode"],
        "media": job["media"],
        "speakers": job["speakers"],
        "error": job["error"],
        "warning": job["warning"],
        "notes": job["notes"],
        "artifacts": _public_artifacts(job),
        "verification": job["verification"],
        "options": job["options"],
        "stage_order": STAGE_ORDER,
        "stage_labels": STAGE_LABELS,
    }


def _public_artifacts(job: dict) -> dict:
    """Expose downloadable names, never absolute server paths."""
    artifacts = job.get("artifacts") or {}
    out: dict = {}
    render = artifacts.get("render") or {}
    if render:
        out["render"] = {
            "has_dubbed": bool(render.get("dubbed")),
            "has_original_audio": bool(render.get("original_audio")),
            "has_mkv": bool(render.get("mkv")),
            "has_audio_only": bool(render.get("audio_only")),
            "has_subtitles": bool(render.get("subtitles")),
            "size_bytes": render.get("size_bytes"),
            "warnings": render.get("warnings", []),
        }
    for key in ("asr", "diarization", "translation", "sync", "audio"):
        if key in artifacts:
            value = dict(artifacts[key])
            if key == "audio":
                value.pop("audio_full", None)
                value.pop("audio_asr", None)
            if key == "sync":
                value.pop("mixed_audio", None)
                value.pop("dialogue_track", None)
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# upload
# --------------------------------------------------------------------------- #
@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    subtitle: UploadFile | None = File(None),
    translated_subtitle: UploadFile | None = File(None),
    target_lang: str = Form("hi"),
    source_lang: str = Form("auto"),
    input_mode: str = Form("auto"),
    autostart: bool = Form(True),
    stop_after: str = Form(""),
    options: str = Form("{}"),
):
    _rate_limit(request)
    if not settings.allow_open_registration and not settings.auth_required:
        raise HTTPException(status_code=403, detail=error_payload("UNAUTHORIZED", "Uploads are disabled on this instance."))
    if queue_service.stats()["queued"] >= settings.max_queue_depth:
        raise HTTPException(
            status_code=503,
            detail=error_payload("RATE_LIMITED", "The processing queue is full.", "Try again in a few minutes."),
        )

    target = (target_lang or "hi").lower()
    source = (source_lang or "auto").lower()
    if not lang_mod.is_supported(target):
        raise HTTPException(status_code=400, detail=error_payload("UNSUPPORTED_LANGUAGE", f"Target '{target}' is not supported."))
    if source != "auto" and not lang_mod.is_supported(source):
        raise HTTPException(status_code=400, detail=error_payload("UNSUPPORTED_LANGUAGE", f"Source '{source}' is not supported."))
    try:
        check_extension(file.filename or "")
    except ValidationFailed as exc:
        raise HTTPException(status_code=exc.status, detail=exc.payload()) from exc

    try:
        parsed_options = json.loads(options or "{}")
        if not isinstance(parsed_options, dict):
            parsed_options = {}
    except json.JSONDecodeError:
        parsed_options = {}

    filename = _safe_filename(file.filename or "movie.mp4")
    job = repo.create_job(
        source_name=filename,
        source_ext=Path(filename).suffix.lower(),
        source_bytes=0,
        source_lang=source,
        target_lang=target,
        options=parsed_options,
        input_mode=input_mode if input_mode in {"auto", "subtitles", "manual"} else "auto",
        client_ip=client_ip(request),
    )
    job_id = job["id"]
    dest = repo.job_dir(job_id) / "source" / filename
    try:
        written = await _save_upload(file, dest, limit_mb=settings.max_upload_mb)
        repo.update_job(job_id, source_bytes=written)
        if subtitle is not None and subtitle.filename:
            sub_ext = Path(subtitle.filename).suffix.lower()
            if sub_ext not in {".srt", ".vtt"}:
                raise ValidationFailed("UNSUPPORTED_FORMAT", "Subtitle files must be .srt or .vtt.")
            await _save_upload(
                subtitle, repo.job_dir(job_id) / "source" / f"source{sub_ext}", limit_mb=8
            )
        if translated_subtitle is not None and translated_subtitle.filename:
            sub_ext = Path(translated_subtitle.filename).suffix.lower()
            if sub_ext not in {".srt", ".vtt"}:
                raise ValidationFailed("UNSUPPORTED_FORMAT", "Subtitle files must be .srt or .vtt.")
            await _save_upload(
                translated_subtitle,
                repo.job_dir(job_id) / "source" / f"translated.{target}{sub_ext}",
                limit_mb=8,
            )
        validated = validate_upload(dest, filename, declared_size=written)
        notes = validate_clip_reference(probe(dest))
        media = validated["media"]
        repo.update_job(
            job_id,
            media=media,
            notes=[{"kind": "info", "message": n} for n in notes],
            progress=3.0,
            stage="extracting_audio",
            status="queued",
        )
        repo.add_event(job_id, "uploading", f"Stored {written/1048576:.1f} MB. Original file kept unchanged.")
    except ValidationFailed as exc:
        repo.delete_job(job_id)
        raise HTTPException(status_code=exc.status, detail=exc.payload()) from exc
    except HTTPException:
        repo.delete_job(job_id)
        raise
    except Exception as exc:  # pragma: no cover
        repo.delete_job(job_id)
        log.exception("upload failed")
        raise HTTPException(status_code=500, detail=error_payload("INTERNAL_ERROR", str(exc))) from exc

    # Manual mode starts with an empty editor: queueing stages now would fail
    # before the user can type anything.
    if input_mode == "manual":
        autostart = False
        repo.update_job(job_id, status="awaiting_input")
        repo.add_event(
            job_id, "transcribing",
            "Manual mode: add the dialogue lines in the studio, then run the stages.",
        )

    stages = None
    final_status = None
    if autostart:
        if stop_after in {"transcribe", "speakers", "translate"}:
            stage_name = {
                "transcribe": "transcribing",
                "speakers": "identifying_speakers",
                "translate": "translating",
            }[stop_after]
            stages = pipeline.AUTO_SEQUENCE[: pipeline.AUTO_SEQUENCE.index(stage_name) + 1]
            final_status = "awaiting_input"
        elif stop_after == "voices":
            stages = pipeline.AUTO_SEQUENCE[: pipeline.AUTO_SEQUENCE.index("generating_voices") + 1]
            final_status = "awaiting_input"
        else:
            stages = list(pipeline.AUTO_SEQUENCE)
        queue_service.enqueue(job_id, stages, final_status=final_status)
    job = ensure_job(job_id)
    return JSONResponse(
        status_code=202,
        content={
            "job": job_payload(job),
            "validation": {
                "format": validated["ext"],
                "duration": media["duration"],
                "video": media["video_streams"][0] if media["video_streams"] else None,
                "audio": media["audio_streams"][0] if media["audio_streams"] else None,
                "advisories": notes,
            },
            "queued": autostart,
        },
    )


# --------------------------------------------------------------------------- #
# granular pipeline endpoints
# --------------------------------------------------------------------------- #
class JobRef(BaseModel):
    job_id: str = Field(..., min_length=8, max_length=64)
    force: bool = False


def _enqueue_stages(job_id: str, stages: list[str], *, force: bool, request: Request) -> dict:
    _rate_limit(request)
    job = ensure_job(job_id)
    if job["status"] == "cancelled":
        raise HTTPException(status_code=409, detail=error_payload("JOB_BUSY", "This project was cancelled."))
    queued = queue_service.enqueue(job_id, stages, force=force)
    repo.update_job(job_id, status="queued")
    repo.add_event(job_id, job["stage"], f"Queued stages: {', '.join(stages)}.")
    return {"job": job_payload(ensure_job(job_id)), "queued": queued, "stages": stages}


@router.post("/analyze")
def analyze(payload: JobRef, request: Request):
    """Probe the file and extract audio (fast, runs inline)."""
    _rate_limit(request)
    job = ensure_job(payload.job_id)
    try:
        info = pipeline.Pipeline(job).extract_audio()
    except pipeline.StageFailure as exc:
        raise HTTPException(status_code=422, detail=error_payload(exc.code, exc.message, exc.hint)) from exc
    return {"job": job_payload(ensure_job(payload.job_id)), "audio": info}


@router.post("/transcribe")
def transcribe(payload: JobRef, request: Request):
    stages = ["extracting_audio", "transcribing"]
    return _enqueue_stages(payload.job_id, stages, force=payload.force, request=request)


@router.post("/speakers")
def speakers(payload: JobRef, request: Request):
    return _enqueue_stages(payload.job_id, ["identifying_speakers"], force=payload.force, request=request)


@router.post("/translate")
def translate(payload: JobRef, request: Request):
    return _enqueue_stages(payload.job_id, ["translating"], force=payload.force, request=request)


@router.post("/generate-voice")
def generate_voice(payload: JobRef, request: Request):
    return _enqueue_stages(payload.job_id, ["generating_voices"], force=payload.force, request=request)


@router.post("/render")
def render(payload: JobRef, request: Request):
    return _enqueue_stages(payload.job_id, ["synchronizing_audio", "rendering"], force=payload.force, request=request)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str, request: Request, payload: JobRef | None = None):
    _rate_limit(request)
    job = ensure_job(job_id)
    stages = list(pipeline.AUTO_SEQUENCE)
    done = set(job["stages_done"])
    remaining = [s for s in stages if s not in done]
    if not remaining:
        remaining = stages
    queue_service.enqueue(job_id, remaining)
    repo.update_job(job_id, status="queued", error=None)
    repo.add_event(job_id, job["stage"], f"Retry requested. Restarting from: {remaining[0]}.", level="warning")
    return {"job": job_payload(ensure_job(job_id)), "stages": remaining}


# --------------------------------------------------------------------------- #
# status / listing / events
# --------------------------------------------------------------------------- #
@router.get("/status/{job_id}")
def status(job_id: str):
    job = ensure_job(job_id)
    events = repo.list_events(job_id, after_id=0, limit=60)
    payload = job_payload(job)
    payload["events"] = events
    payload["queue"] = queue_service.stats()
    return payload


@router.get("/jobs")
def list_jobs(limit: int = 50, status_filter: str | None = None):
    limit = max(1, min(200, limit))
    jobs = repo.list_jobs(limit=limit, status=status_filter)
    return {
        "jobs": [job_payload(j) for j in jobs],
        "queue": queue_service.stats(),
        "retention_hours": settings.retention_hours,
    }


@router.get("/jobs/{job_id}/events")
async def events_stream(job_id: str, request: Request, after: int = 0):
    """Server-sent events: real stage/progress updates, one per work unit."""
    ensure_job(job_id)

    async def generator():
        last_id = after
        last_progress = None
        terminal = {"completed", "failed", "cancelled"}
        for _ in range(3600):  # ~30 minutes max
            if await request.is_disconnected():
                break
            job = repo.get_job(job_id)
            if not job:
                yield "event: gone\ndata: {}\n\n"
                break
            rows = repo.list_events(job_id, after_id=last_id, limit=50)
            for row in rows:
                last_id = row["id"]
                yield f"event: log\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            snapshot = {
                "status": job["status"],
                "stage": job["stage"],
                "progress": job["progress"],
                "stages_done": job["stages_done"],
                "error": job["error"],
                "updated_at": job["updated_at"],
            }
            if snapshot["progress"] != last_progress or rows:
                last_progress = snapshot["progress"]
                yield f"event: progress\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            if job["status"] in terminal:
                yield f"event: done\ndata: {json.dumps(job_payload(job), ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(1.2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# --------------------------------------------------------------------------- #
# segments (studio editing)
# --------------------------------------------------------------------------- #
class SegmentPatch(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str | None = None
    translated_text: str | None = None
    speaker: str | None = None


@router.get("/jobs/{job_id}/segments")
def get_segments(job_id: str):
    job = ensure_job(job_id)
    segments = repo.get_segments(job_id)
    return {
        "job_id": job_id,
        "target_lang": job["target_lang"],
        "source_lang": job["source_lang"],
        "speakers": job["speakers"],
        "segments": [s.to_dict() for s in segments],
    }


@router.patch("/jobs/{job_id}/segments/{idx}")
def patch_segment(job_id: str, idx: int, patch: SegmentPatch):
    ensure_job(job_id)
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    if "start" in fields:
        fields["start_sec"] = float(fields.pop("start"))
    if "end" in fields:
        fields["end_sec"] = float(fields.pop("end"))
    if fields.get("start_sec") is not None and fields.get("end_sec") is not None:
        if fields["end_sec"] <= fields["start_sec"]:
            raise HTTPException(status_code=400, detail="A line must end after it starts.")
    if "speaker" in fields:
        fields["speaker"] = str(fields["speaker"])[:32]
    segment = repo.update_segment(job_id, idx, **fields)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    # edited text invalidates previously generated audio
    if "translated_text" in fields or "text" in fields:
        repo.add_event(job_id, "queued", f"Line {idx + 1} edited; its audio will be regenerated on the next voice step.")
    return {"segment": segment.to_dict()}


class SegmentsBulk(BaseModel):
    segments: list[dict]


@router.put("/jobs/{job_id}/segments")
def replace_segments(job_id: str, payload: SegmentsBulk):
    """Manual mode: the user pastes/edits their own dialogue, or fixes ASR output."""
    from ..models import Segment

    ensure_job(job_id)
    if not payload.segments:
        raise HTTPException(status_code=400, detail="No segments supplied.")
    segments = []
    for i, item in enumerate(payload.segments[:5000]):
        start = float(item.get("start", item.get("start_sec", 0)))
        end = float(item.get("end", item.get("end_sec", start + 1.5)))
        segments.append(
            Segment(
                id=i,
                start=max(0.0, start),
                end=max(start + 0.2, end),
                text=str(item.get("text", ""))[:2000],
                translated_text=str(item.get("translated_text", ""))[:2000],
                speaker=str(item.get("speaker") or f"SPEAKER_{1:02d}")[:32],
            )
        )
    repo.replace_segments(job_id, segments)
    repo.add_event(job_id, "transcribing", f"Dialogue replaced with {len(segments)} manual lines.")
    speakers = sorted({s.speaker for s in segments})
    repo.update_job(
        job_id,
        speakers=[{"id": s, "label": "Speaker " + s.split("_")[-1], "gender": "unknown", "segments": 0, "voice": ""} for s in speakers],
    )
    return {"job_id": job_id, "segments": [s.to_dict() for s in segments]}


class SpeakerVoice(BaseModel):
    speaker: str
    voice: str
    gender: str | None = None


@router.post("/jobs/{job_id}/voices")
def set_speaker_voices(job_id: str, payload: list[SpeakerVoice]):
    job = ensure_job(job_id)
    speakers = job["speakers"] or []
    by_id = {s["id"]: s for s in speakers}
    voice_map = dict((job["options"] or {}).get("voice_map") or {})
    for item in payload:
        speaker = by_id.get(item.speaker) or {"id": item.speaker, "label": item.speaker, "segments": 0}
        speaker["voice"] = item.voice
        if item.gender:
            speaker["gender"] = item.gender
        by_id[item.speaker] = speaker
        voice_map[item.speaker] = item.voice
    options = dict(job["options"] or {})
    options["voice_map"] = voice_map
    repo.update_job(job_id, speakers=list(by_id.values()), options=options)
    return {"speakers": list(by_id.values())}


# --------------------------------------------------------------------------- #
# media / download
# --------------------------------------------------------------------------- #

def _artifact_path(job: dict, kind: str) -> tuple[Path, str]:
    render = (job.get("artifacts") or {}).get("render") or {}
    lang = job["target_lang"]
    mapping = {
        "dubbed": (render.get("dubbed"), f"bhashaflix_{lang}.mp4"),
        "original_audio": (render.get("original_audio"), "bhashaflix_original_audio.mp4"),
        "mkv": (render.get("mkv"), f"bhashaflix_{lang}_multitrack.mkv"),
        "audio_only": (render.get("audio_only"), f"bhashaflix_{lang}.m4a"),
    }
    if kind.startswith("subtitle_"):
        sub_key = kind[len("subtitle_"):]
        subtitles = render.get("subtitles") or {}
        path = subtitles.get(sub_key)
        if not path:
            raise HTTPException(status_code=404, detail="That subtitle track is not available.")
        return Path(path), Path(path).name
    if kind not in mapping:
        raise HTTPException(status_code=400, detail=f"Unknown artifact '{kind}'.")
    raw, name = mapping[kind]
    if not raw:
        raise HTTPException(
            status_code=404,
            detail=error_payload("JOB_NOT_FOUND", f"The {kind} file is not available for this project yet."),
        )
    return Path(raw), name


@router.get("/media/{job_id}")
def media(job_id: str, request: Request, track: str = "dubbed"):
    """Player stream (supports Range so seeking works)."""
    job = ensure_job(job_id)
    kind = "original_audio" if track in {"original", "source"} else "dubbed"
    path, name = _artifact_path(job, kind)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rendered file is missing from storage.")
    return range_response(request, path, filename=name, inline=True)


@router.get("/download/{job_id}")
def download(job_id: str, request: Request, kind: str = "dubbed"):
    job = ensure_job(job_id)
    path, name = _artifact_path(job, kind)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File is no longer on the server (it may have expired).")
    if kind.startswith("subtitle_"):
        return range_response(request, path, filename=name, inline=False)
    return range_response(request, path, filename=f"{Path(job['source_name']).stem}_{job['target_lang']}{path.suffix}", inline=False)


@router.get("/jobs/{job_id}/subtitles/{kind}.vtt", response_class=PlainTextResponse)
def subtitles_vtt(job_id: str, kind: str = "translated"):
    from ..services.srt import to_vtt

    job = ensure_job(job_id)
    segments = repo.get_segments(job_id)
    cues = [
        {"start": s.start, "end": s.end, "text": s.text, "translated_text": s.translated_text}
        for s in segments
    ]
    return PlainTextResponse(to_vtt(cues, translated=kind != "source"), media_type="text/vtt")


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #
@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = ensure_job(job_id)
    ok = repo.delete_job(job_id, hard=True)
    if not ok:
        raise HTTPException(status_code=404, detail=error_payload("JOB_NOT_FOUND"))
    log.info("deleted job %s (%s)", job_id, job["source_name"])
    return {"deleted": True, "job_id": job_id}


# --------------------------------------------------------------------------- #
# voices
# --------------------------------------------------------------------------- #
class VoicePreviewRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=400)
    lang: str = Field(..., min_length=2, max_length=8)
    voice: str = Field(..., min_length=2, max_length=120)


@router.get("/voices")
def voices(lang: str | None = None):
    langs = [lang] if lang else [item["code"] for item in lang_mod.target_languages()]
    catalog = voice_catalog(langs)
    return {
        "catalog": catalog["languages"],
        "engines": catalog["engines"],
        "note": "Only voices from engines that are actually installed are listed.",
    }


@router.post("/voice-preview")
def voice_preview(payload: VoicePreviewRequest):
    lang = payload.lang.lower()
    if not lang_mod.is_supported(lang):
        raise HTTPException(status_code=400, detail=error_payload("UNSUPPORTED_LANGUAGE"))
    digest = abs(hash((payload.text, lang, payload.voice))) % (10**12)
    out = settings.tmp_dir / f"preview_{digest}.wav"
    if not out.exists():
        try:
            preview(payload.text[:400], lang, payload.voice, out)
        except TTSError as exc:
            raise HTTPException(status_code=422, detail=error_payload(exc.code, str(exc), exc.hint)) from exc
    return FileResponse(
        out,
        media_type="audio/wav",
        filename=out.name,
        headers={"Cache-Control": "private, max-age=600"},
    )
