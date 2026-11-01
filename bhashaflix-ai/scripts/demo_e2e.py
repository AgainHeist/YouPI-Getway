#!/usr/bin/env python3
"""End-to-end demo: create a clip, dub it into Hindi, verify the picture.

This talks to a *running* backend over HTTP, exactly like the browser does, so
it proves the real API path (upload -> stages -> render -> download).

    # terminal 1
    uvicorn backend.app:app --host 0.0.0.0 --port 8000
    # terminal 2
    python scripts/demo_e2e.py --target hi

The sample clip is synthesized dialogue-free audio beds (a centre "voice" tone
plus wide "music" noise) so the separation step can be checked objectively.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import ffmpeg_executable  # noqa: E402

ENGLISH = [
    (0.4, 2.2, "Where are you going tonight?"),
    (2.6, 4.4, "I am going to the market with my brother."),
    (4.8, 6.6, "Do you want to come with us?"),
    (6.9, 8.4, "Yes, but I must be home before midnight."),
]
HINDI = [
    (0.4, 2.2, "तुम आज रात कहाँ जा रहे हो?"),
    (2.6, 4.4, "मैं अपने भाई के साथ बाज़ार जा रहा हूँ।"),
    (4.8, 6.6, "क्या तुम हमारे साथ आना चाहते हो?"),
    (6.9, 8.4, "हाँ, लेकिन मुझे आधी रात से पहले घर पहुँचना है।"),
]


def srt(cues) -> str:
    def ts(seconds: float) -> str:
        h, m = int(seconds // 3600), int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        if ms == 1000:
            s, ms = s + 1, 0
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for i, (start, end, text) in enumerate(cues, 1):
        out += [str(i), f"{ts(start)} --> {ts(end)}", text, ""]
    return "\n".join(out)


def make_clip(path: Path, seconds: float = 9.0) -> Path:
    ffmpeg = ffmpeg_executable()
    if not ffmpeg:
        sys.exit("FFmpeg not found. `pip install imageio-ffmpeg` or install ffmpeg.")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:seed=7:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:seed=11:sample_rate=48000:duration={seconds}",
        "-filter_complex",
        "[1:a]volume=0.55,pan=stereo|c0=c0|c1=c0[dlg];"
        "[2:a]volume=0.12[bgL];[3:a]volume=0.12[bgR];"
        "[bgL][bgR]join=inputs=2:channel_layout=stereo[bg];"
        "[dlg][bg]amix=inputs=2:duration=longest:normalize=0[a]",
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-t", str(seconds), str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        sys.exit(proc.stderr.decode()[-1500:])
    return path


def multipart(fields: dict[str, str], files: list[tuple[str, Path, str]]) -> tuple[bytes, str]:
    boundary = "----bhashaflix" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += str(value).encode() + b"\r\n"
    for name, path, content_type in files:
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def post(url: str, body: bytes, content_type: str):
    request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code}: {exc.read().decode()[:2000]}")


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser(description="BhashaFlix AI end-to-end demo")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="backend base URL")
    parser.add_argument("--target", default="hi", help="target language code")
    parser.add_argument("--source", default="en", help="source language code")
    parser.add_argument("--seconds", type=float, default=9.0)
    parser.add_argument("--keep-clip", action="store_true", help="keep the generated sample clip")
    args = parser.parse_args()

    work = ROOT / "sample_media"
    clip = make_clip(work / "sample_movie.mp4", args.seconds)
    source_srt = work / "sample_movie.en.srt"
    target_srt = work / f"sample_movie.{args.target}.srt"
    source_srt.write_text(srt(ENGLISH), encoding="utf-8")
    target_srt.write_text(srt(HINDI), encoding="utf-8")
    print(f"clip      : {clip} ({clip.stat().st_size/1024:.0f} KB)")
    print(f"subtitles : {source_srt.name} + {target_srt.name}")

    health = get_json(f"{args.api}/api/health")
    print(f"backend   : {health['instance']} · ffmpeg {'ok' if health['ffmpeg'] else 'MISSING'} · gpu {health['gpu']}")

    fields = {
        "target_lang": args.target,
        "source_lang": args.source,
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
    created = post(f"{args.api}/api/upload", body, content_type)
    job_id = created["job"]["id"]
    print(f"job       : {job_id} (queued={created['queued']})")

    last_stage = None
    deadline = time.time() + 900
    while time.time() < deadline:
        job = get_json(f"{args.api}/api/status/{job_id}")
        stage = job["stage"]
        if stage != last_stage:
            print(f"  [{job['progress']:5.1f}%] {stage}")
            last_stage = stage
        if job["status"] in {"completed", "failed", "awaiting_input"}:
            break
        time.sleep(1.0)

    job = get_json(f"{args.api}/api/status/{job_id}")
    if job["status"] != "completed":
        print(json.dumps(job.get("error"), ensure_ascii=False, indent=2))
        return 1

    verification = job.get("verification", {})
    print("\n--- result ---")
    print(f"status              : {job['status']}")
    print(f"video identical     : {verification.get('video_identical')}")
    print(f"original md5        : {verification.get('original_video_md5')}")
    print(f"rendered md5        : {verification.get('rendered_video_md5')}")
    level = verification.get("audio_level", {})
    print(f"dialogue level      : peak {level.get('peak_db')} dB / mean {level.get('mean_db')} dB")
    sync = job.get("artifacts", {}).get("sync", {})
    print(f"separation          : {sync.get('engine')} ({sync.get('quality')})")
    print(f"speakers            : {[s['id'] + ':' + str(s.get('voice')) for s in job.get('speakers', [])]}")
    print(f"player              : {args.api}/player.html?job={job_id}")
    print(f"download            : {args.api}/download.html?job={job_id}")
    for warning in sync.get("warnings", []):
        print(f"warning             : {warning}")

    if not args.keep_clip:
        for path in (clip, source_srt, target_srt):
            path.unlink(missing_ok=True)
        try:
            work.rmdir()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
