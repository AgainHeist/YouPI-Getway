"""Shared test fixtures.

A real (tiny) movie clip is generated with FFmpeg so every test exercises the
genuine pipeline — no mocks, no canned JSON.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

_TEST_STORAGE = tempfile.mkdtemp(prefix="bhashaflix-tests-")
os.environ.setdefault("BFLIX_STORAGE_DIR", _TEST_STORAGE)
os.environ["BFLIX_WORKER_THREADS"] = "1"
os.environ["BFLIX_RETENTION_HOURS"] = "0"
os.environ["BFLIX_RATE_LIMIT_PER_MIN"] = "100000"
os.environ.pop("BFLIX_API_TOKEN", None)
os.environ.setdefault("BFLIX_TTS_ENGINE", "espeak-ng")

from backend.config import ffmpeg_executable  # noqa: E402

ENGLISH_CUES = [
    (0.4, 2.2, "Where are you going tonight?"),
    (2.6, 4.4, "I am going to the market with my brother."),
    (4.8, 6.6, "Do you want to come with us?"),
    (6.9, 8.4, "Yes, but I must be home before midnight."),
]

HINDI_CUES = [
    (0.4, 2.2, "तुम आज रात कहाँ जा रहे हो?"),
    (2.6, 4.4, "मैं अपने भाई के साथ बाज़ार जा रहा हूँ।"),
    (4.8, 6.6, "क्या तुम हमारे साथ आना चाहते हो?"),
    (6.9, 8.4, "हाँ, लेकिन मुझे आधी रात से पहले घर पहुँचना है।"),
]


def _srt(cues, offset: float = 0.0) -> str:
    def ts(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        if ms == 1000:
            s, ms = s + 1, 0
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for i, (start, end, text) in enumerate(cues, start=1):
        out += [str(i), f"{ts(start + offset)} --> {ts(end + offset)}", text, ""]
    return "\n".join(out)


def make_test_clip(path: Path, *, seconds: float = 9.0, stereo_center_dialogue: bool = True) -> Path:
    """Build a tiny MP4 whose 'dialogue' is centre-panned and 'music' is wide.

    That lets the centre-suppression separator be tested for real: the centre
    tone should disappear from the background, the wide noise should not.
    """
    ffmpeg = ffmpeg_executable()
    assert ffmpeg, "FFmpeg is required for the test suite"
    path.parent.mkdir(parents=True, exist_ok=True)
    if stereo_center_dialogue:
        audio_filter = (
            f"[1:a]volume=0.55,pan=stereo|c0=c0|c1=c0[dlg];"
            f"[2:a]volume=0.12[bgL];[3:a]volume=0.12[bgR];"
            f"[dlg][bgL][bgR]amerge=inputs=2[wrong]"
        )
        # amerge of 3 inputs is invalid; build explicitly instead
        audio_filter = (
            f"[1:a]volume=0.55,pan=stereo|c0=c0|c1=c0[dlg];"
            f"[2:a]volume=0.12[bgL];[3:a]volume=0.12[bgR];"
            f"[bgL][bgR]join=inputs=2:channel_layout=stereo[bg];"
            f"[dlg][bg]amix=inputs=2:duration=longest:normalize=0[a]"
        )
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:seed=7:sample_rate=48000:duration={seconds}",
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:seed=11:sample_rate=48000:duration={seconds}",
            "-filter_complex", audio_filter,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-t", str(seconds), str(path),
        ]
    else:
        cmd = [
            ffmpeg, "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-ac", "1",
            "-t", str(seconds), str(path),
        ]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    return path


@pytest.fixture(scope="session")
def test_clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "sample_movie.mp4"
    return make_test_clip(path)


@pytest.fixture(scope="session")
def mono_clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "mono_movie.mp4"
    return make_test_clip(path, seconds=6.0, stereo_center_dialogue=False)


@pytest.fixture(scope="session")
def source_srt(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("subs") / "source.srt"
    path.write_text(_srt(ENGLISH_CUES), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def hindi_srt(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("subs") / "translated.hi.srt"
    path.write_text(_srt(HINDI_CUES), encoding="utf-8")
    return path


@pytest.fixture()
def job_factory(test_clip, source_srt, hindi_srt):
    """Create a job with an uploaded clip and subtitle sidecars, like the API does."""
    from backend.services import repo

    created = []

    def _make(*, target_lang: str = "hi", source_lang: str = "en", mode: str = "subtitles",
              options: dict | None = None, clip: Path | None = None,
              with_translation: bool = True) -> str:
        job = repo.create_job(
            source_name=(clip or test_clip).name,
            source_ext=".mp4",
            source_bytes=(clip or test_clip).stat().st_size,
            source_lang=source_lang,
            target_lang=target_lang,
            options=options or {"separate": "center-suppression"},
            input_mode=mode,
        )
        job_id = job["id"]
        dest = repo.job_dir(job_id) / "source" / (clip or test_clip).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((clip or test_clip).read_bytes())
        (repo.job_dir(job_id) / "source" / "source.srt").write_text(source_srt.read_text(), encoding="utf-8")
        if with_translation:
            (repo.job_dir(job_id) / "source" / f"translated.{target_lang}.srt").write_text(
                hindi_srt.read_text(), encoding="utf-8"
            )
        created.append(job_id)
        return job_id

    yield _make
    for job_id in created:
        repo.delete_job(job_id, hard=True)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def espeak_available() -> bool:
    from backend.engines.tts import EspeakTTS

    ok, _ = EspeakTTS.dependencies_ok()
    return ok
