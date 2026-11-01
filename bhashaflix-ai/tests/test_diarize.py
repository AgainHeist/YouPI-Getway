"""Speaker identification tests on synthetic two-voice audio."""
from __future__ import annotations

import numpy as np
import pytest

from backend.engines.diarize import SpectralDiarizer, normalize_assignments
from backend.engines.media import write_wav


def _voice(freq: float, seconds: float, sr: int = 16000) -> np.ndarray:
    """A crude two-formant 'voice' — different spectral envelopes per speaker."""
    t = np.arange(int(seconds * sr)) / sr
    glottal = sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, 9))
    formant = 0.4 * np.sin(2 * np.pi * 3.5 * freq * t) + 0.2 * np.sin(2 * np.pi * 7.0 * freq * t)
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 2.5 * t)
    signal = (glottal * 0.3 + formant) * env
    return (0.3 * signal / np.max(np.abs(signal))).astype(np.float32)


def test_two_voices_get_two_speaker_ids(tmp_path):
    sr = 16000
    segments = []
    samples = []
    cursor = 0.0
    for i in range(8):
        freq = 120.0 if i % 2 == 0 else 240.0
        clip = _voice(freq, 1.0, sr)
        samples.append(clip)
        samples.append(np.zeros(int(0.25 * sr), dtype=np.float32))  # pause between lines
        segments.append({"id": i, "start": cursor, "end": cursor + 1.0, "text": f"line {i}"})
        cursor += 1.25
    audio = np.concatenate(samples)
    path = tmp_path / "two_voices.wav"
    write_wav(path, audio, sr, channels=1)

    result = SpectralDiarizer().run(path, segments)
    labels = result.assignments
    assert len(labels) == len(segments)
    # alternating voices must land in two clusters, consistently
    assert len(set(labels)) == 2, labels
    assert labels[0] != labels[1]
    assert labels[0] == labels[2] == labels[4]
    assert labels[1] == labels[3] == labels[5]
    assert result.confidence <= 0.6, "the fallback must not overstate its confidence"
    assert any("review" in w.lower() or "clustered" in w.lower() for w in result.warnings)
    assert all(speaker["id"].startswith("SPEAKER_") for speaker in result.speakers)


def test_normalize_assignments_orders_by_first_appearance():
    assert normalize_assignments(["B", "A", "B"]) == ["SPEAKER_01", "SPEAKER_02", "SPEAKER_01"]


def test_single_speaker_audio_stays_one_speaker(tmp_path):
    sr = 16000
    clip = _voice(150.0, 6.0, sr)
    segments = [
        {"id": i, "start": i * 1.5, "end": i * 1.5 + 1.2, "text": "same voice"}
        for i in range(4)
    ]
    path = tmp_path / "one_voice.wav"
    write_wav(path, clip, sr, channels=1)
    result = SpectralDiarizer().run(path, segments)
    assert len(set(result.assignments)) == 1


def test_diarizer_handles_silent_audio(tmp_path):
    sr = 16000
    path = tmp_path / "silence.wav"
    write_wav(path, np.zeros(sr * 3, dtype=np.float32), sr, channels=1)
    segments = [{"id": 0, "start": 0.0, "end": 1.0, "text": ""}]
    result = SpectralDiarizer().run(path, segments)
    assert result.assignments == ["SPEAKER_01"]
    assert result.confidence <= 0.3
