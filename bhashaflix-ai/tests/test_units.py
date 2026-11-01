"""Unit tests for the pure logic: subtitles, languages, validation, mixing, DSP."""
from __future__ import annotations

import numpy as np
import pytest

from backend.engines import dsp
from backend.services import languages as lang
from backend.services import mix as mix_mod
from backend.services.srt import parse_subtitles, to_srt, to_vtt
from backend.services.validation import ValidationFailed, check_extension, check_size


SRT = """1
00:00:01,000 --> 00:00:03,500
Where are you going?

2
00:00:04,000 --> 00:00:06,000
<i>I am going</i> to the market.
"""


def test_srt_parsing_keeps_timing_and_strips_markup():
    cues = parse_subtitles(SRT)
    assert len(cues) == 2
    assert cues[0]["start"] == pytest.approx(1.0)
    assert cues[0]["end"] == pytest.approx(3.5)
    assert cues[1]["text"] == "I am going to the market."


def test_srt_roundtrip_and_vtt():
    cues = parse_subtitles(SRT)
    for cue in cues:
        cue["translated_text"] = "अनुवाद"
    srt = to_srt(cues, translated=True)
    reparsed = parse_subtitles(srt)
    assert len(reparsed) == 2
    assert reparsed[0]["text"] == "अनुवाद"
    assert to_vtt(cues).startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:03.500" in to_vtt(cues)


def test_inverted_cues_are_repaired():
    cues = parse_subtitles("1\n00:00:05,000 --> 00:00:04,000\nhmm\n")
    assert cues[0]["end"] > cues[0]["start"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Where are you going tonight?", "en"),
        ("तुम आज रात कहाँ जा रहे हो?", "hi"),
        ("নমস্কার বন্ধু, তুমি কোথায় যাচ্ছ?", "bn"),
        ("நண்பர்களே, எங்கே போகிறீர்கள்?", "ta"),
        ("안녕하세요, 어디 가세요?", "ko"),
        ("¿Dónde vas esta noche?", "es"),
    ],
)
def test_text_language_detection(text, expected):
    code, confidence = lang.detect_text_language(text)
    assert code == expected
    assert 0.0 < confidence <= 1.0


def test_bhojpuri_is_flagged_separately():
    code, _ = lang.detect_text_language("हमनी के बाबूजी कहाँ गइल बाड़न, हमार भाई कहाँ बा?")
    assert code in {"hi", "bho"}


def test_language_catalogue_is_consistent():
    codes = [item["code"] for item in lang.LANGUAGES]
    assert len(codes) == len(set(codes))
    for required in ("hi", "en", "bho", "ur", "ta", "te", "bn", "es", "fr", "ja", "ko"):
        assert required in codes
    for item in lang.LANGUAGES:
        assert item["nllb"] and item["en"] and item["native"]


def test_extension_and_size_limits():
    assert check_extension("movie.MP4") == ".mp4"
    assert check_extension("movie.mkv") == ".mkv"
    with pytest.raises(ValidationFailed) as excinfo:
        check_extension("movie.exe")
    assert excinfo.value.code == "UNSUPPORTED_FORMAT"
    with pytest.raises(ValidationFailed):
        check_size(10**12)


def test_tempo_fitting_clamps_both_directions():
    tempo, overflow = mix_mod.compute_tempo(natural=3.0, slot=3.0)
    assert tempo == pytest.approx(1.0) and overflow is False
    tempo, overflow = mix_mod.compute_tempo(natural=4.5, slot=3.0)
    assert 1.0 < tempo <= 1.45 and overflow is True
    tempo, _ = mix_mod.compute_tempo(natural=1.0, slot=3.0)
    assert tempo == pytest.approx(1.0), "short lines must not be slowed down unnaturally"


def test_dialogue_track_never_overlaps():
    sr = 48000
    segments = [
        {"id": 0, "start": 0.0, "end": 1.0},
        {"id": 1, "start": 1.2, "end": 2.2},
        {"id": 2, "start": 2.4, "end": 3.4},
    ]
    clips = [
        mix_mod.FittedClip(0, 0.0, 1.0, 1.0, 1.9, 1.45, 1.0, False, None),
        mix_mod.FittedClip(1, 1.2, 2.2, 1.0, 1.9, 1.45, 1.0, False, None),
        mix_mod.FittedClip(2, 2.4, 3.4, 1.0, 1.1, 1.0, 1.0, False, None),
    ]
    # replace the file paths with real tiny clips so placement can be measured
    import tempfile
    from pathlib import Path

    from backend.engines.media import write_wav

    tmp = Path(tempfile.mkdtemp())
    tone = (0.4 * np.sin(2 * np.pi * 300 * np.arange(sr) / sr)).astype(np.float32)
    for i, clip in enumerate(clips):
        path = tmp / f"c{i}.wav"
        write_wav(path, tone, sr, channels=1)
        clip.path = path

    track, placed, warnings = mix_mod.build_dialogue_track(segments, clips, 3.6, sample_rate=sr)
    assert track.shape[0] == int(3.6 * sr)
    ends = [c.placed_end for c in placed]
    starts = [c.start for c in placed]
    for i in range(len(placed) - 1):
        assert ends[i] <= starts[i + 1] + 1e-6, "lines must not overlap"
        assert ends[i] <= segments[i]["end"] + 0.31, "lines must respect the overflow tolerance"


def test_duck_envelope_lowers_background_only_while_speaking():
    sr = 48000
    dialogue = np.zeros(sr * 2, dtype=np.float32)
    dialogue[int(0.5 * sr):int(1.5 * sr)] = 0.3
    env = mix_mod.duck_envelope(dialogue, sample_rate=sr, duck_db=-6.0)
    assert env.shape[0] == dialogue.size
    assert env[0] > 0.98, "background must not be ducked before anyone speaks"
    assert env[int(1.0 * sr)] < 0.55, "background must be ducked during dialogue"
    assert env[-1] > 0.95, "background must recover afterwards"


def test_mix_never_clips():
    sr = 8000
    bg = np.full((sr, 2), 0.7, dtype=np.float32)
    dlg = np.full(sr, 0.7, dtype=np.float32)
    mixed, metrics = mix_mod.mix_tracks(bg, dlg, sample_rate=sr, duck=False)
    assert float(np.max(np.abs(mixed))) <= 1.0
    assert metrics["limiter_applied"] is True


def test_agglomerative_clustering_separates_two_voices():
    rng = np.random.default_rng(3)
    base_a = rng.normal(0.0, 1.0, 20).astype(np.float32)
    base_b = -base_a + rng.normal(0.0, 0.2, 20).astype(np.float32)
    a = base_a + rng.normal(0.0, 0.05, size=(6, 20)).astype(np.float32)
    b = base_b + rng.normal(0.0, 0.05, size=(6, 20)).astype(np.float32)
    embeddings = np.vstack([a, b])
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    labels = dsp.agglomerative_cluster(embeddings, threshold=0.1, max_clusters=4)
    assert len(set(labels[:6])) == 1
    assert len(set(labels[6:])) == 1
    assert labels[0] != labels[-1]


def test_mfcc_and_embedding_shapes():
    sr = 16000
    tone = np.sin(2 * np.pi * 180 * np.arange(sr) / sr).astype(np.float32)
    ceps = dsp.mfcc(tone, sample_rate=sr)
    assert ceps.shape[1] == 13
    assert ceps.shape[0] > 10
    emb = dsp.segment_embedding(tone, sample_rate=sr)
    assert emb.shape == (39,)
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-4


def test_pitch_estimate_is_in_human_range():
    from backend.engines.diarize import estimate_pitch

    sr = 16000
    t = np.arange(sr) / sr
    voice = sum(0.3 * np.sin(2 * np.pi * 120 * k * t) / k for k in range(1, 6)).astype(np.float32)
    pitch = estimate_pitch(voice, sr)
    assert pitch is not None and 90 < pitch < 160


def test_resample_and_fade():
    x = np.ones(1000, dtype=np.float32)
    out = dsp.resample_linear(x, 1000, 2000)
    assert out.shape[0] == 2000
    faded = dsp.apply_fade(x, 1000, fade_ms=10)
    assert faded[0] == pytest.approx(0.0, abs=1e-6)
    assert faded[-1] == pytest.approx(0.0, abs=1e-6)


def test_decode_falls_back_to_ffmpeg_when_pyav_is_missing(monkeypatch, tmp_path):
    """Phones/Termux have no PyAV: decoding must then go through the ffmpeg pipe."""
    import subprocess
    import sys

    from backend.config import ffmpeg_executable
    from backend.engines import media

    ffmpeg = ffmpeg_executable()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:sample_rate=48000:duration=1",
            "-ac", "2", str(wav),
        ],
        capture_output=True,
        check=True,
    )
    monkeypatch.setitem(sys.modules, "av", None)  # makes `import av` raise ImportError
    samples, rate = media.decode_to_numpy(wav, channels=1, sample_rate=16000)
    assert rate == 16000
    assert samples.shape == (16000, 1)
    assert 0.05 < float(np.abs(samples).max()) < 0.2  # the sine is at -18 dBFS
    # and the probe still works without PyAV (ffprobe or `ffmpeg -i` parsing)
    assert media.probe(wav).duration == pytest.approx(1.0, abs=0.1)
