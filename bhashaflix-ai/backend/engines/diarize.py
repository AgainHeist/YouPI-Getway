"""Speaker identification (diarization).

Priority: pyannote.audio (best, needs an HF token + we accept the model terms)
-> built-in spectral clustering on MFCC embeddings (runs anywhere, CPU only,
honest about its limits) -> single speaker.

Speaker IDs are assigned in order of first appearance ("SPEAKER_01" is the
first voice heard) and stay stable for the whole movie.  Everything is editable
in the studio, because automatic diarization does fail — especially on
overlapping speech, whisper, shouting and heavy music.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import settings
from . import dsp

log = logging.getLogger("bhashaflix.diarize")


@dataclass
class DiarizationResult:
    assignments: list[str]          # one speaker id per input segment
    engine: str
    speakers: list[dict]            # [{id, label, gender, segments, pitch_hz}]
    confidence: float               # 0..1, deliberately pessimistic
    warnings: list[str]


class DiarizerError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


def speaker_label(index: int) -> str:
    return f"SPEAKER_{index + 1:02d}"


class BaseDiarizer:
    name = "base"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return False, "not implemented"

    def run(self, audio_path: Path, segments: list[dict]) -> DiarizationResult:
        raise NotImplementedError


class PyannoteDiarizer(BaseDiarizer):
    name = "pyannote"

    def __init__(self, token: str | None = None):
        token = token or settings.hf_token
        if not token:
            raise DiarizerError(
                "GPU_UNAVAILABLE",
                "pyannote needs a Hugging Face token (BFLIX_HF_TOKEN) to download its weights.",
                "Create a token at huggingface.co and accept the pyannote/speaker-diarization-3.1 model terms.",
            )
        from pyannote.audio import Pipeline  # type: ignore

        self.pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import pyannote.audio  # noqa: F401
        except Exception:
            return False, "pip install pyannote.audio (+ HF token + accept model terms)"
        return True, "ready"

    def run(self, audio_path: Path, segments: list[dict]) -> DiarizationResult:
        annotation = self.pipeline(str(audio_path))
        turns = [
            (turn.start, turn.end, label)
            for turn, _, label in annotation.itertracks(yield_label=True)
        ]
        assignments: list[str] = []
        for seg in segments:
            mid = (seg["start"] + seg["end"]) / 2.0
            best_label, best_overlap = None, 0.0
            for start, end, label in turns:
                overlap = min(end, seg["end"]) - max(start, seg["start"])
                if overlap > best_overlap:
                    best_label, best_overlap = label, overlap
            assignments.append(best_label or "SPEAKER_00")
        # normalise to first-appearance order
        order: list[str] = []
        for a in assignments:
            if a not in order:
                order.append(a)
        mapping = {old: speaker_label(i) for i, old in enumerate(order)}
        assignments = [mapping.get(a, speaker_label(0)) for a in assignments]
        speakers = _speaker_summary(assignments, audio_path, segments)
        return DiarizationResult(
            assignments=assignments,
            engine=self.name,
            speakers=speakers,
            confidence=0.8,
            warnings=[],
        )


class SpectralDiarizer(BaseDiarizer):
    """MFCC embedding + average-linkage clustering, numpy only."""

    name = "spectral-clustering"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import numpy  # noqa: F401
            import av  # noqa: F401
        except Exception:
            return False, "needs numpy + audio decoding (PyAV or system ffmpeg)"
        return True, "ready"

    def run(self, audio_path: Path, segments: list[dict]) -> DiarizationResult:
        from .media import decode_to_numpy

        warnings: list[str] = []
        audio, rate = decode_to_numpy(audio_path, channels=1, sample_rate=16000)
        audio = audio.reshape(-1) if audio.ndim > 1 else audio
        if audio.size == 0:
            raise DiarizerError("AUDIO_SYNC_FAILED", "Diarization could not read the extracted audio.")

        embeddings: list[np.ndarray] = []
        valid_idx: list[int] = []
        for i, seg in enumerate(segments):
            start = max(0, int(seg["start"] * rate))
            end = min(audio.size, int(seg["end"] * rate))
            if end - start < int(0.25 * rate):
                continue  # too short to characterise a voice
            clip = audio[start:end]
            peak = float(np.max(np.abs(clip))) if clip.size else 0.0
            if peak < 1e-4:
                continue  # silence
            clip = clip / peak
            embeddings.append(dsp.segment_embedding(clip, sample_rate=rate))
            valid_idx.append(i)
        if len(embeddings) < 2:
            assignments = [speaker_label(0) for _ in segments]
            return DiarizationResult(
                assignments=assignments,
                engine=self.name,
                speakers=_speaker_summary(assignments, audio_path, segments),
                confidence=0.2,
                warnings=["Too few usable speech segments to separate speakers; everything is Speaker 1."],
            )

        matrix = np.vstack(embeddings)
        labels = dsp.agglomerative_cluster(matrix, threshold=0.16, max_clusters=8)
        raw = ["__none__"] * len(segments)
        for label, seg_index in zip(labels, valid_idx):
            raw[seg_index] = f"c{label}"
        # Fill skipped (short/silent) segments with the neighbour's label.
        last = next((x for x in raw if x != "__none__"), speaker_label(0))
        for i, value in enumerate(raw):
            if value == "__none__":
                raw[i] = last
            else:
                last = value
        order: list[str] = []
        for value in raw:
            if value not in order:
                order.append(value)
        mapping = {old: speaker_label(i) for i, old in enumerate(order)}
        assignments = [mapping[v] for v in raw]
        speaker_count = len(order)
        if speaker_count >= 5:
            warnings.append(
                f"{speaker_count} distinct voices detected — verify the speaker labels in the studio; "
                "clustering can split one voice when the delivery changes a lot."
            )
        warnings.append(
            "Speakers were clustered from spectral features (no neural diarization model installed). "
            "Please review the assignment before rendering."
        )
        confidence = 0.55 if speaker_count <= 3 else 0.4
        return DiarizationResult(
            assignments=assignments,
            engine=self.name,
            speakers=_speaker_summary(assignments, audio_path, segments),
            confidence=confidence,
            warnings=warnings,
        )


class SingleSpeakerDiarizer(BaseDiarizer):
    name = "single-speaker"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return True, "always available"

    def run(self, audio_path: Path, segments: list[dict]) -> DiarizationResult:
        assignments = [speaker_label(0) for _ in segments]
        return DiarizationResult(
            assignments=assignments,
            engine=self.name,
            speakers=_speaker_summary(assignments, audio_path, segments),
            confidence=0.1,
            warnings=["Speaker separation was skipped; every line uses Speaker 1."],
        )


def estimate_pitch(x: np.ndarray, sample_rate: int) -> float | None:
    """Median F0 via autocorrelation over voiced frames (heuristic, not ID)."""
    frame = int(0.04 * sample_rate)
    hop = int(0.02 * sample_rate)
    if x.size < frame * 3:
        return None
    f0s: list[float] = []
    lo, hi = int(sample_rate / 350), int(sample_rate / 70)
    for start in range(0, x.size - frame, hop):
        f = x[start:start + frame].astype(np.float64)
        if np.sqrt(np.mean(f ** 2)) < 0.01:
            continue
        f = f - f.mean()
        corr = np.correlate(f, f, mode="full")[frame - 1:]
        if corr[0] <= 0:
            continue
        corr = corr / corr[0]
        window = corr[lo:hi]
        if window.size == 0:
            continue
        peak = int(np.argmax(window)) + lo
        if corr[peak] > 0.3:
            f0s.append(sample_rate / peak)
    if len(f0s) < 5:
        return None
    return float(np.median(f0s))


def guess_gender(pitch_hz: float | None) -> str:
    """Very rough; used only to pick a plausible male/female voice."""
    if pitch_hz is None:
        return "unknown"
    if pitch_hz < 155:
        return "male"
    if pitch_hz > 185:
        return "female"
    return "unknown"


def _speaker_summary(assignments: list[str], audio_path: Path, segments: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for value in assignments:
        counts[value] = counts.get(value, 0) + 1
    pitch_by_speaker: dict[str, float] = {}
    try:
        from .media import decode_to_numpy

        audio, rate = decode_to_numpy(audio_path, channels=1, sample_rate=16000)
        audio = audio.reshape(-1) if audio.ndim > 1 else audio
        for speaker in counts:
            pieces = []
            for seg, label in zip(segments, assignments):
                if label != speaker:
                    continue
                start, end = int(seg["start"] * rate), int(seg["end"] * rate)
                if end > start:
                    pieces.append(audio[start:end])
            if pieces:
                pitch = estimate_pitch(np.concatenate(pieces), rate)
                if pitch:
                    pitch_by_speaker[speaker] = round(pitch, 1)
    except Exception as exc:  # pragma: no cover - audio decoding is best effort
        log.debug("pitch estimation skipped: %s", exc)
    out = []
    for speaker, count in sorted(counts.items()):
        pitch = pitch_by_speaker.get(speaker)
        out.append(
            {
                "id": speaker,
                "label": "Speaker " + str(int(speaker.split("_")[-1])),
                "gender": guess_gender(pitch),
                "pitch_hz": pitch,
                "segments": count,
                "voice": "",
            }
        )
    return out


def available_diarizers() -> list[dict]:
    out = []
    for cls in (PyannoteDiarizer, SpectralDiarizer, SingleSpeakerDiarizer):
        ok, reason = cls.dependencies_ok()
        out.append({"engine": cls.name, "available": ok, "reason": reason})
    return out


def build_diarizer(engine: str | None = None) -> BaseDiarizer:
    requested = (engine or settings.diarize_engine or "auto").lower()
    order = {
        "pyannote": [PyannoteDiarizer],
        "spectral": [SpectralDiarizer],
        "spectral-clustering": [SpectralDiarizer],
        "single": [SingleSpeakerDiarizer],
        "none": [SingleSpeakerDiarizer],
    }.get(requested, [PyannoteDiarizer, SpectralDiarizer, SingleSpeakerDiarizer])
    for cls in order:
        ok, _ = cls.dependencies_ok()
        if not ok:
            continue
        try:
            return cls()
        except DiarizerError as exc:
            if requested == "pyannote":
                raise
            log.info("diarizer %s unavailable: %s", cls.name, exc)
        except Exception as exc:
            log.warning("diarizer %s failed to load: %s", cls.name, exc)
    return SingleSpeakerDiarizer()


def normalize_assignments(assignments: list[str]) -> list[str]:
    order: list[str] = []
    for value in assignments:
        if value not in order:
            order.append(value)
    mapping = {old: speaker_label(i) for i, old in enumerate(order)}
    return [mapping.get(value, speaker_label(0)) for value in assignments]


def diarization_quality(assignments: list[str], segments: list[dict]) -> dict:
    """Cheap statistics that help the UI flag doubtful results."""
    counts: dict[str, int] = {}
    for value in assignments:
        counts[value] = counts.get(value, 0) + 1
    total = max(1, len(assignments))
    shares = {k: round(v / total, 3) for k, v in counts.items()}
    rare = [k for k, v in counts.items() if v <= max(1, int(0.02 * total))]
    return {
        "speaker_count": len(counts),
        "shares": shares,
        "rare_speakers": rare,
        "review_recommended": bool(rare) or len(counts) > 4,
        "note": "Automatic diarization is a best-effort estimate. Every label can be corrected in the studio.",
    }


def _hz_to_semitones(hz: float) -> float:
    return 12 * math.log2(hz / 440.0) if hz > 0 else 0.0
