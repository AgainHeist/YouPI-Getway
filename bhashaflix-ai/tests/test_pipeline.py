"""End-to-end pipeline tests against a real generated clip."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from backend.config import ffmpeg_executable, settings
from backend.engines.media import decode_to_numpy, probe
from backend.services import pipeline, repo


def _spectrum_energy(path: Path, freq: float, *, tolerance: float = 12.0) -> float:
    """Energy near `freq` Hz in an audio file (dB, relative to full scale)."""
    audio, rate = decode_to_numpy(path, channels=1, sample_rate=48000)
    mono = audio.reshape(-1)
    window = np.hanning(mono.size)
    spectrum = np.abs(np.fft.rfft(mono * window))
    freqs = np.fft.rfftfreq(mono.size, 1 / rate)
    band = (freqs > freq - tolerance) & (freqs < freq + tolerance)
    energy = float(np.sum(spectrum[band] ** 2))
    return 10 * np.log10(max(energy, 1e-12))


def _frame_hashes(path: Path) -> list[str]:
    proc = subprocess.run(
        [ffmpeg_executable(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
         "-map", "0:v:0", "-c", "copy", "-f", "framemd5", "-"],
        capture_output=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-800:]
    return [
        line.split(",")[-1].strip()
        for line in proc.stdout.decode().splitlines()
        if line and not line.startswith("#")
    ]


def test_full_pipeline_keeps_original_video_and_dubs_hindi(job_factory):
    job_id = job_factory()
    pipeline.run_full_job(job_id)
    job = repo.get_job(job_id)

    assert job["status"] == "completed", job["error"]
    assert job["stage"] == "completed"
    assert job["progress"] == 100.0

    render = job["artifacts"]["render"]
    dubbed = Path(render["dubbed"])
    original_audio = Path(render["original_audio"])
    assert dubbed.exists() and dubbed.stat().st_size > 10_000
    assert original_audio.exists()

    info = probe(dubbed)
    assert len(info.video_streams) == 1
    assert len(info.audio_streams) == 2, "dub + original audio track expected"
    assert info.audio_streams[0].language == "hin"
    assert info.audio_streams[1].language == "eng"
    # the picture is untouched: identical duration, resolution and codec
    source = probe(Path(job["dir"]) / "source" / job["source_name"])
    assert info.video_streams[0].codec == source.video_streams[0].codec
    assert info.video_streams[0].width == source.video_streams[0].width
    assert info.video_streams[0].height == source.video_streams[0].height
    assert abs(info.duration - source.duration) < 0.5

    verification = job["verification"]
    assert verification["video_identical"] is True
    assert verification["original_video_md5"] == verification["rendered_video_md5"]
    assert verification["audio_level"]["audible"] is True

    # per-frame hashes must match exactly, frame for frame
    assert _frame_hashes(dubbed) == _frame_hashes(Path(source.path))

    segments = repo.get_segments(job_id)
    assert len(segments) == 4
    assert all(s.translated_text for s in segments)
    assert all(s.tempo for s in segments)
    assert job["artifacts"]["sync"]["metrics"]["overlaps"] == 0


def test_dubbed_speech_is_actually_present_and_synced(job_factory):
    job_id = job_factory()
    pipeline.run_full_job(job_id)
    job = repo.get_job(job_id)
    mixed = Path(job["artifacts"]["sync"]["mixed_audio"])
    audio, rate = decode_to_numpy(mixed, channels=1, sample_rate=48000)
    mono = audio.reshape(-1)

    segments = repo.get_segments(job_id)
    for segment in segments:
        start = int(segment.start * rate)
        end = min(mono.size, int(segment.end * rate))
        window = mono[start:end]
        assert window.size > 0
        peak = float(np.max(np.abs(window)))
        assert peak > 0.01, f"line {segment.id} is silent in the mix"
    # after the last cue (+ the 0.3 s overflow tolerance) the track goes quiet
    tail = mono[int(8.85 * rate):]
    if tail.size > 1000:
        assert float(np.max(np.abs(tail))) < 0.2, "dubbed speech ran past its cue"  


def test_center_suppression_removes_centre_dialogue_tone(job_factory):
    job_id = job_factory(options={"separate": "center-suppression"})
    pipeline.run_full_job(job_id)
    job = repo.get_job(job_id)
    work = Path(job["dir"]) / "work"
    original = work / "audio_full.wav"
    background = work / "background.wav"
    assert background.exists()

    before = _spectrum_energy(original, 440.0)
    after = _spectrum_energy(background, 440.0)
    assert after < before - 6.0, f"centre tone not suppressed ({before:.1f} -> {after:.1f} dB)"

    # the wide (panned) noise floor must survive
    noise_before = _spectrum_energy(original, 3000.0)
    noise_after = _spectrum_energy(background, 3000.0)
    assert noise_after > noise_before - 12.0


def test_mono_source_is_honest_about_ducking(mono_clip, job_factory):
    job_id = job_factory(clip=mono_clip, options={"separate": "center-suppression"})
    pipeline.run_full_job(job_id)
    job = repo.get_job(job_id)
    assert job["status"] == "completed"
    sync = job["artifacts"]["sync"]
    assert sync["engine"] == "ducking"
    assert sync["quality"] == "fallback"
    assert any("mono" in w.lower() for w in sync["warnings"])


def test_missing_asr_engine_fails_honestly(job_factory):
    job_id = job_factory(mode="auto", with_translation=False)
    # remove the imported subtitles so the ASR stage must run for real
    for path in (Path(repo.get_job(job_id)["dir"]) / "source").glob("*.srt"):
        path.unlink()
    with pytest.raises(pipeline.StageFailure) as excinfo:
        pipeline.run_full_job(job_id, stages=["extracting_audio", "transcribing"])
    failure = excinfo.value
    assert failure.code in {"ASR_UNAVAILABLE", "TRANSCRIBE_FAILED", "NO_DIALOGUE"}
    assert failure.hint, "a missing model must come with an actionable hint"
    job = repo.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"]["code"] == failure.code


def test_missing_translator_fails_honestly(job_factory):
    from backend.engines.translate import TRANSLATOR_CLASSES

    if any(cls.dependencies_ok()[0] for cls in TRANSLATOR_CLASSES):
        pytest.skip("a real translation engine is installed on this machine")
    job_id = job_factory(with_translation=False, options={"translate_engine": "nllb"})
    with pytest.raises(pipeline.StageFailure) as excinfo:
        pipeline.run_full_job(job_id, stages=["extracting_audio", "transcribing", "translating"])
    assert excinfo.value.code == "TRANSLATE_UNAVAILABLE"
    assert "transformers" in (excinfo.value.hint or "") or "nllb" in (excinfo.value.hint or "").lower()


def test_stage_order_is_enforced(job_factory):
    job_id = job_factory()
    with pytest.raises(pipeline.StageFailure) as excinfo:
        pipeline.run_full_job(job_id, stages=["translating"])
    assert excinfo.value.code == "STAGE_OUT_OF_ORDER"


def test_job_progress_is_monotonic(job_factory):
    job_id = job_factory()
    pipeline.run_full_job(job_id)
    events = repo.list_events(job_id, limit=500)
    progress_values = [e["progress"] for e in events if e["progress"] is not None]
    assert progress_values, "progress events are required (no fake percentages)"
    assert max(progress_values) == pytest.approx(100.0, abs=0.01)
    assert all(p >= 0 for p in progress_values)


def test_original_file_is_never_modified(job_factory):
    job_id = job_factory()
    job = repo.get_job(job_id)
    source_path = Path(job["dir"]) / "source" / job["source_name"]
    before = source_path.read_bytes()
    pipeline.run_full_job(job_id)
    assert source_path.read_bytes() == before
    assert source_path.stat().st_size == job["source_bytes"]
