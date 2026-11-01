#!/usr/bin/env python3
"""Seed a *running* backend with two finished demo projects.

A fresh install has an empty library, so the UI's "Continue watching" and
History pages look broken even though the pipeline works.  This script fills
them with two real, fully-rendered jobs so anyone can open the player and hear
the result immediately.

    # terminal 1
    python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
    # terminal 2
    python scripts/seed_demo_library.py

Project 1 - "subtitles" mode: a 9 s clip plus English/Hindi subtitle files, the
whole 9-stage pipeline runs without any AI model installed.
Project 2 - "manual" mode: a 12 s two-speaker clip; dialogue is typed in,
two different voices are assigned to the two speakers, then rendered.

Both projects are verified the same way a user would check them: the video
stream md5 of the source and the dub must match.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.config import ffmpeg_executable  # noqa: E402
from demo_e2e import ENGLISH, HINDI, get_json, make_clip, multipart, post, srt  # noqa: E402

LINES = [
    (0.6, 2.6, "SPEAKER_01", "Where are you going tonight?", "तुम आज रात कहाँ जा रहे हो?"),
    (3.0, 5.0, "SPEAKER_02", "I am going to the market with my brother.", "मैं अपने भाई के साथ बाज़ार जा रहा हूँ।"),
    (5.4, 7.4, "SPEAKER_01", "Do you want to come with us?", "क्या तुम हमारे साथ आना चाहते हो?"),
    (7.8, 9.8, "SPEAKER_02", "Yes, but I must be home before midnight.", "हाँ, लेकिन मुझे आधी रात से पहले घर पहुँचना है।"),
]


def request_json(method: str, url: str, payload: dict | list | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = response.read()
            return json.loads(body.decode()) if body else {}
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} on {method} {url}: {exc.read().decode()[:1500]}")
        raise SystemExit(1)


def wait(api: str, job_id: str, terminal: tuple[str, ...] = ("completed",), timeout: float = 600.0) -> dict:
    last = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = get_json(f"{api}/api/status/{job_id}")
        stage = f"{job['stage']} {job['progress']:.0f}%"
        if stage != last:
            print(f"    {stage}")
            last = stage
        if job["status"] in terminal or job["status"] == "failed":
            return job
        time.sleep(1.0)
    return get_json(f"{api}/api/status/{job_id}")


def report(job: dict) -> bool:
    verification = job.get("verification") or {}
    sync = (job.get("artifacts") or {}).get("sync") or {}
    ok = job["status"] == "completed" and verification.get("video_identical") is True
    print(f"    status={job['status']} video_identical={verification.get('video_identical')} "
          f"md5={verification.get('rendered_video_md5')}")
    voices = [f"{s['id']}:{s.get('voice')}" for s in job.get("speakers") or []]
    print(f"    speakers={voices}")
    print(f"    separation={sync.get('engine')} ({sync.get('quality')})")
    for warning in sync.get("warnings") or []:
        print(f"    warning: {warning}")
    if not ok and job.get("error"):
        print(f"    error: {json.dumps(job['error'], ensure_ascii=False)}")
    return ok


def make_two_speaker_clip(path: Path, seconds: float = 12.0) -> Path:
    """Picture + wide background bed + centre-panned 'dialogue' tones."""
    ffmpeg = ffmpeg_executable()
    if not ffmpeg:
        raise SystemExit("FFmpeg not found. `pip install imageio-ffmpeg` first.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tones = [(190, 0.6), (240, 3.0), (190, 5.4), (240, 7.8)]
    inputs: list[str] = []
    for freq, _start in tones:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration=2"]
    inputs += [
        "-f", "lavfi", "-i", f"anoisesrc=color=brown:seed=3:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=color=brown:seed=9:sample_rate=48000:duration={seconds}",
    ]
    delays = "".join(
        f"[{i + 1}:a]volume=0.45,adelay={int(start * 1000)}|{int(start * 1000)}[d{i + 1}];"
        for i, (_freq, start) in enumerate(tones)
    )
    dialogue = "".join(f"[d{i + 1}]" for i in range(len(tones)))
    bg_index = len(tones) + 1
    graph = (
        f"{delays}{dialogue}amix=inputs={len(tones)}:duration=longest:normalize=0,"
        "pan=stereo|c0=c0|c1=c0[dlg];"
        f"[{bg_index}:a]volume=0.10[bgL];[{bg_index + 1}:a]volume=0.10[bgR];"
        "[bgL][bgR]join=inputs=2:channel_layout=stereo[bg];"
        "[dlg][bg]amix=inputs=2:duration=longest:normalize=0[a]"
    )
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=854x480:rate=25:duration={seconds}",
        *inputs,
        "-filter_complex", graph,
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-t", str(seconds), str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode()[-2000:])
    return path


def seed_subtitles(api: str, work: Path) -> str:
    print("\n[1/2] subtitles mode - full pipeline, no AI model needed")
    clip = make_clip(work / "sample_movie.mp4", 9.0)
    source_srt = work / "sample_movie.en.srt"
    target_srt = work / "sample_movie.hi.srt"
    source_srt.write_text(srt(ENGLISH), encoding="utf-8")
    target_srt.write_text(srt(HINDI), encoding="utf-8")
    fields = {
        "target_lang": "hi",
        "source_lang": "en",
        "input_mode": "subtitles",
        "autostart": "true",
        "stop_after": "",
        "options": json.dumps({"separate": "center-suppression"}),
    }
    files = [
        ("file", clip, "video/mp4"),
        ("subtitle", source_srt, "text/plain"),
        ("translated_subtitle", target_srt, "text/plain"),
    ]
    body, content_type = multipart(fields, files)
    created = post(f"{api}/api/upload", body, content_type)
    job_id = created["job"]["id"]
    print(f"    job {job_id}")
    report(wait(api, job_id))
    return job_id


def seed_two_speakers(api: str, work: Path) -> str:
    print("\n[2/2] manual mode - two speakers, two voices, real render")
    clip = make_two_speaker_clip(work / "two_speakers.mp4", 12.0)
    body, content_type = multipart(
        {"target_lang": "hi", "source_lang": "en", "input_mode": "manual"},
        [("file", clip, "video/mp4")],
    )
    created = post(f"{api}/api/upload", body, content_type)
    job_id = created["job"]["id"]
    print(f"    job {job_id} ({created['job']['status']})")

    segments = [
        {
            "start": start,
            "end": end,
            "speaker": speaker,
            "text": english,
            "translated_text": hindi,
        }
        for start, end, speaker, english, hindi in LINES
    ]
    if request_json("PUT", f"{api}/api/jobs/{job_id}/segments", {"segments": segments}).get("segments") is None:
        print("    could not save dialogue lines")
        return job_id

    catalog = get_json(f"{api}/api/voices?lang=hi").get("catalog", {}).get("hi", [])
    if not catalog:
        print("    no TTS engine available - skipping voice assignment")
        return job_id
    ids = [voice["id"] for voice in catalog]
    first = next((v for v in ids if v.endswith("+m3")), ids[0])
    second = next((v for v in ids if v.endswith("+f3")), ids[min(1, len(ids) - 1)])
    if second == first:
        second = next((v for v in ids if v != first), first)
    request_json(
        "POST",
        f"{api}/api/jobs/{job_id}/voices",
        [
            {"speaker": "SPEAKER_01", "voice": first, "gender": "male"},
            {"speaker": "SPEAKER_02", "voice": second, "gender": "female"},
        ],
    )
    request_json("POST", f"{api}/api/generate-voice", {"job_id": job_id, "force": True})
    paused = wait(api, job_id, terminal=("awaiting_input",))
    if paused["status"] != "awaiting_input":
        report(paused)
        return job_id
    request_json("POST", f"{api}/api/render", {"job_id": job_id, "force": True})
    report(wait(api, job_id))
    return job_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo projects into a running BhashaFlix AI backend")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="backend base URL")
    parser.add_argument("--only", choices=("subtitles", "speakers", "both"), default="both")
    parser.add_argument("--clean", action="store_true", help="delete the generated clips afterwards")
    args = parser.parse_args()

    health = get_json(f"{args.api}/api/health")
    print(f"backend: {health['instance']} · ffmpeg {'ok' if health['ffmpeg'] else 'MISSING'} · gpu {health['gpu']}")

    work = ROOT / "sample_media"
    ids = []
    if args.only in ("subtitles", "both"):
        ids.append(seed_subtitles(args.api, work))
    if args.only in ("speakers", "both"):
        ids.append(seed_two_speakers(args.api, work))

    print("\n--- library ---")
    for job in get_json(f"{args.api}/api/jobs").get("jobs", []):
        print(f"  {job['id'][:8]}  {job['status']:11}  {job['source_name'][:28]:28}  {job['target_lang']}")
    print(f"  player: {args.api}/player.html?job={ids[0] if ids else ''}")

    if args.clean:
        for path in work.glob("*"):
            path.unlink(missing_ok=True)
        try:
            work.rmdir()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
