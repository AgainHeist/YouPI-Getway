"""Repository layer: all SQL lives here (jobs, segments, events)."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Iterable

from ..config import settings
from ..db import get_conn, json_dump, json_load, now, row_to_dict
from ..models import STAGE_LABELS, STAGE_ORDER, Segment, error_payload


# --------------------------------------------------------------------------- #
# job records
# --------------------------------------------------------------------------- #
def new_job_id() -> str:
    return uuid.uuid4().hex


def job_dir(job_id: str) -> Path:
    """Resolve a job directory, refusing anything that is not a plain hex id."""
    if not job_id or any(c not in "0123456789abcdef" for c in job_id) or len(job_id) != 32:
        raise ValueError("invalid job id")
    return settings.jobs_dir / job_id


def create_job(
    *,
    job_id: str | None = None,
    source_name: str,
    source_ext: str,
    source_bytes: int,
    source_lang: str = "auto",
    target_lang: str = "hi",
    options: dict | None = None,
    input_mode: str = "auto",
    client_ip: str | None = None,
) -> dict:
    job_id = job_id or new_job_id()
    ts = now()
    conn = get_conn()
    conn.execute(
        """INSERT INTO jobs (id, created_at, updated_at, status, stage, progress,
                             source_name, source_ext, source_bytes, source_lang,
                             target_lang, options, input_mode, client_ip)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, ts, ts, "queued", "queued", 0.0,
            source_name, source_ext, source_bytes,
            source_lang, target_lang, json_dump(options or {}),
            input_mode, client_ip,
        ),
    )
    for sub in ("source", "work", "out", "tts", "logs"):
        (job_dir(job_id) / sub).mkdir(parents=True, exist_ok=True)
    add_event(job_id, "queued", "Job created. Original file will be kept untouched.", progress=0)
    return get_job(job_id)


def get_job(job_id: str, *, include_deleted: bool = False) -> dict | None:
    try:
        path = job_dir(job_id)
    except ValueError:
        return None
    row = get_conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    if row["deleted"] and not include_deleted:
        return None
    job = row_to_dict(row)
    job["options"] = json_load(job.get("options"), {})
    job["stages_done"] = json_load(job.get("stages_done"), [])
    job["media"] = json_load(job.get("media"), {})
    job["speakers"] = json_load(job.get("speakers"), [])
    job["artifacts"] = json_load(job.get("artifacts"), {})
    job["verification"] = json_load(job.get("verification"), {})
    job["notes"] = json_load(job.get("notes"), [])
    job["error"] = json_load(job.get("error"), None)
    job["warning"] = json_load(job.get("warning"), None)
    job["dir"] = str(path)
    job["stage_label"] = STAGE_LABELS.get(job["stage"], {"en": job["stage"], "hi": job["stage"]})
    job["stage_index"] = STAGE_ORDER.index(job["stage"]) if job["stage"] in STAGE_ORDER else -1
    job["stage_total"] = len(STAGE_ORDER)
    return job


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    prepared: dict[str, object] = {}
    for key, value in fields.items():
        if key in {"options", "media", "speakers", "artifacts", "verification", "notes", "error", "warning", "stages_done"}:
            prepared[key] = json_dump(value)
        elif key in {"progress", "source_bytes"}:
            prepared[key] = float(value) if key == "progress" else int(value)
        else:
            prepared[key] = value
    prepared["updated_at"] = now()
    cols = ", ".join(f"{k}=?" for k in prepared)
    get_conn().execute(f"UPDATE jobs SET {cols} WHERE id=?", (*prepared.values(), job_id))


def list_jobs(*, limit: int = 50, status: str | None = None, order: str = "created_at DESC") -> list[dict]:
    order = order if order in {"created_at DESC", "created_at ASC", "updated_at DESC"} else "created_at DESC"
    sql = "SELECT id FROM jobs WHERE deleted=0"
    params: list[object] = []
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += f" ORDER BY {order} LIMIT ?"
    params.append(int(limit))
    ids = [r["id"] for r in get_conn().execute(sql, params).fetchall()]
    return [j for j in (get_job(i) for i in ids) if j]


def mark_stage(job_id: str, stage: str, progress: float, message: str | None = None) -> None:
    job = get_job(job_id)
    if not job:
        return
    done = [s for s in job["stages_done"] if s != stage]
    if stage in STAGE_ORDER and stage != "completed":
        pass
    if progress >= 99.5 and stage in STAGE_ORDER:
        if stage not in done:
            done.append(stage)
    fields: dict[str, object] = {
        "stage": stage,
        "progress": max(0.0, min(100.0, round(float(progress), 2))),
        "status": "running",
        "stages_done": done,
    }
    update_job(job_id, **fields)
    if message:
        add_event(job_id, stage, message, progress=progress)


def finish_job(job_id: str, *, status: str, error: dict | None = None, warning: dict | None = None) -> None:
    job = get_job(job_id)
    done = list(job["stages_done"]) if job else []
    if status == "completed" and "completed" not in done:
        done.append("completed")
    update_job(
        job_id,
        status=status,
        stage="completed" if status == "completed" else ("failed" if status == "failed" else job["stage"]),
        progress=100.0 if status == "completed" else (job["progress"] if job else 0.0),
        stages_done=done,
        error=error,
        warning=warning,
    )


def delete_job(job_id: str, *, hard: bool = True) -> bool:
    job = get_job(job_id, include_deleted=True)
    if not job:
        return False
    get_conn().execute("DELETE FROM segments WHERE job_id=?", (job_id,))
    get_conn().execute("DELETE FROM events WHERE job_id=?", (job_id,))
    get_conn().execute("DELETE FROM voice_previews WHERE job_id=?", (job_id,))
    get_conn().execute("DELETE FROM jobs WHERE id=?", (job_id,))
    path = Path(job["dir"])
    if hard and path.exists() and settings.jobs_dir in path.parents:
        shutil.rmtree(path, ignore_errors=True)
    return True


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
def add_event(job_id: str, stage: str, message: str, *, level: str = "info", progress: float | None = None) -> None:
    get_conn().execute(
        "INSERT INTO events (job_id, ts, stage, message, level, progress) VALUES (?,?,?,?,?,?)",
        (job_id, now(), stage, message, level, progress),
    )


def list_events(job_id: str, *, after_id: int = 0, limit: int = 200) -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id ASC LIMIT ?",
        (job_id, int(after_id), int(limit)),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def add_note(job_id: str, note: dict) -> None:
    job = get_job(job_id)
    notes = list(job["notes"]) if job else []
    notes.append(note)
    update_job(job_id, notes=notes[-40:])


# --------------------------------------------------------------------------- #
# segments
# --------------------------------------------------------------------------- #
def replace_segments(job_id: str, segments: Iterable[Segment]) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM segments WHERE job_id=?", (job_id,))
    conn.executemany(
        """INSERT INTO segments (job_id, idx, start_sec, end_sec, text, translated_text,
                                 speaker, confidence, tts_duration, tempo, flags)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                job_id, s.id, s.start, s.end, s.text, s.translated_text, s.speaker,
                s.confidence, s.tts_duration, s.tempo, json_dump(s.flags),
            )
            for s in segments
        ],
    )


def get_segments(job_id: str) -> list[Segment]:
    rows = get_conn().execute(
        "SELECT * FROM segments WHERE job_id=? ORDER BY idx ASC", (job_id,)
    ).fetchall()
    return [Segment.from_row(r) for r in rows]


def segments_available(job_id: str) -> bool:
    row = get_conn().execute("SELECT COUNT(*) AS c FROM segments WHERE job_id=?", (job_id,)).fetchone()
    return bool(row and row["c"])


def update_segment(job_id: str, idx: int, **fields) -> Segment | None:
    allowed = {"start_sec", "end_sec", "text", "translated_text", "speaker", "flags", "tempo"}
    sets, vals = [], []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        sets.append(f"{key}=?")
        vals.append(json_dump(value) if key == "flags" else value)
    if not sets:
        return None
    vals.extend([job_id, idx])
    get_conn().execute(f"UPDATE segments SET {', '.join(sets)} WHERE job_id=? AND idx=?", vals)
    rows = get_segments(job_id)
    return next((s for s in rows if s.id == idx), None)


def segments_stats(job_id: str) -> dict:
    rows = get_conn().execute(
        "SELECT COUNT(*) AS total, MIN(start_sec) AS first, MAX(end_sec) AS last FROM segments WHERE job_id=?",
        (job_id,),
    ).fetchone()
    return {
        "total": rows["total"] if rows else 0,
        "first_start": rows["first"] if rows else None,
        "last_end": rows["last"] if rows else None,
    }


# --------------------------------------------------------------------------- #
# retention
# --------------------------------------------------------------------------- #
def expired_jobs(retention_hours: float) -> list[dict]:
    cutoff = now() - retention_hours * 3600.0
    rows = get_conn().execute(
        "SELECT id FROM jobs WHERE created_at < ? AND deleted=0 "
        "AND status NOT IN ('running','queued')",
        (cutoff,),
    ).fetchall()
    return [{"id": r["id"]} for r in rows]


def storage_usage_bytes() -> int:
    total = 0
    for path in settings.jobs_dir.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def error_for(code: str, detail: str | None = None, hint: str | None = None) -> dict:
    return error_payload(code, detail, hint)
