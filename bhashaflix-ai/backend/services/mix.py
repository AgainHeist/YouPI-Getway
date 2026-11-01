"""Timing fit + audio mixing.

The dub must land on the original dialogue timestamps.  For every line we:
  1. measure the synthesized clip,
  2. compute the tempo factor needed to fit the original slot,
  3. clamp it (never destroy intelligibility by stretching too far),
  4. place it at the original start time with short fades,
  5. guarantee that two lines never overlap.

Then dialogue and preserved background are mixed, optional ducking is applied
while somebody speaks, and a peak-safe master is written.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..config import settings
from ..engines import dsp
from ..engines.media import MediaError, change_tempo, decode_to_numpy, write_wav

log = logging.getLogger("bhashaflix.mix")


@dataclass
class FittedClip:
    segment_id: int
    start: float
    end: float
    slot: float
    natural: float
    tempo: float
    placed_end: float
    clipped: bool
    path: Path | None = None


@dataclass
class MixResult:
    dialogue_path: Path
    final_path: Path
    clips: list[FittedClip] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def compute_tempo(natural: float, slot: float) -> tuple[float, bool]:
    """Return (tempo_factor, will_overflow) for fitting `natural` into `slot`."""
    if slot <= 0 or natural <= 0:
        return 1.0, False
    ratio = natural / slot
    if ratio > 1.0:
        tempo = min(ratio, settings.max_tempo_stretch)
        return round(tempo, 4), ratio > settings.max_tempo_stretch
    if ratio < 0.8:
        # Clip is much shorter than the slot: let it breathe instead of
        # stretching speech down (slow speech sounds unnatural).
        return 1.0, False
    return 1.0, False


def fit_clip(
    source: Path,
    slot: float,
    tempo: float,
    dest: Path,
    *,
    sample_rate: int = 48000,
) -> tuple[Path, float]:
    """Apply tempo and conform the clip to 48 kHz mono.  Returns (path, duration)."""
    if abs(tempo - 1.0) > 0.005:
        try:
            change_tempo(source, dest, tempo, sample_rate=sample_rate, channels=1)
        except MediaError:
            log.warning("atempo failed for %s, falling back to plain resample", source)
            change_tempo(source, dest, 1.0, sample_rate=sample_rate, channels=1)
    else:
        change_tempo(source, dest, 1.0, sample_rate=sample_rate, channels=1)
    audio, _ = decode_to_numpy(dest, channels=1, sample_rate=sample_rate)
    return dest, audio.shape[0] / float(sample_rate)


def build_dialogue_track(
    segments: list[dict],
    clips: list[FittedClip],
    total_duration: float,
    *,
    sample_rate: int = 48000,
    work_dir: Path | None = None,
    overflow_tolerance: float = 0.30,
) -> tuple[np.ndarray, list[FittedClip], list[str]]:
    """Place every fitted clip on one timeline at its original offset.

    A line may overrun its own cue by `overflow_tolerance` seconds (natural
    speech does), but it may never run into the next line: that would create
    the overlapping dialogue the spec forbids.
    """
    warnings: list[str] = []
    n_samples = max(1, int(total_duration * sample_rate))
    track = np.zeros(n_samples, dtype=np.float32)
    ordered = sorted(zip(segments, clips), key=lambda pair: pair[1].start)
    previous_end = -1.0
    for idx, (segment, clip) in enumerate(ordered):
        if clip.path is None:
            continue
        audio, _ = decode_to_numpy(clip.path, channels=1, sample_rate=sample_rate)
        audio = audio.reshape(-1)
        if audio.size == 0:
            continue
        start = max(clip.start, previous_end + 0.02 if previous_end > 0 else 0.0)
        if idx + 1 < len(ordered):
            next_start = ordered[idx + 1][1].start
        else:
            next_start = total_duration
        slot_end = float(segment.get("end", clip.start + clip.slot) or (clip.start + clip.slot))
        latest_end = min(next_start - 0.02, slot_end + overflow_tolerance)
        latest_end = max(latest_end, start + 0.15)
        max_len = int(round((latest_end - start) * sample_rate))
        if max_len <= 0:
            warnings.append(f"Line {segment.get('id')} had no room in the timeline and was skipped.")
            continue
        segment_audio = audio[:max_len]
        if segment_audio.size < audio.size:
            # fade the truncation instead of cutting mid-word abruptly
            fade = min(int(0.06 * sample_rate), segment_audio.size // 2)
            if fade > 0:
                segment_audio = segment_audio.copy()
                segment_audio[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            clip.clipped = True
        segment_audio = dsp.apply_fade(segment_audio, sample_rate, 10.0)
        offset = int(round(start * sample_rate))
        end = min(n_samples, offset + segment_audio.size)
        if end - offset < segment_audio.size:
            segment_audio = segment_audio[: end - offset]
        track[offset:end] += segment_audio
        clip.placed_end = round((offset + segment_audio.size) / sample_rate, 3)
        previous_end = clip.placed_end
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    if peak > 0.99:
        track *= 0.99 / peak
        warnings.append("Dialogue peak was normalised to avoid clipping in the mix.")
    return track, clips, warnings


def duck_envelope(
    dialogue: np.ndarray,
    *,
    sample_rate: int = 48000,
    duck_db: float | None = None,
    attack: float = 0.10,
    release: float = 0.18,
) -> np.ndarray:
    """Gain curve that lowers the background while dialogue is present."""
    if dialogue.size == 0:
        return np.ones(1, dtype=np.float32)
    duck_db = settings.background_duck_db if duck_db is None else duck_db
    gain = dsp.db_to_linear(duck_db)
    frame = max(1, int(sample_rate * 0.02))
    n_frames = int(np.ceil(dialogue.size / frame))
    padded = np.zeros(n_frames * frame, dtype=np.float32)
    padded[: dialogue.size] = dialogue
    frames = padded.reshape(n_frames, frame)
    active = (np.abs(frames).max(axis=1) > 0.01).astype(np.float32)
    # smooth with a one-pole filter in both directions
    smoothed = np.zeros_like(active)
    a_att = 1.0 - np.exp(-1.0 / max(1.0, attack * sample_rate / frame))
    a_rel = 1.0 - np.exp(-1.0 / max(1.0, release * sample_rate / frame))
    current = 0.0
    for i, value in enumerate(active):
        coeff = a_att if value > current else a_rel
        current += coeff * (value - current)
        smoothed[i] = current
    envelope_frames = 1.0 + (gain - 1.0) * smoothed
    envelope = np.repeat(envelope_frames, frame)[: dialogue.size].astype(np.float32)
    return envelope


def mix_tracks(
    background: np.ndarray,
    dialogue: np.ndarray,
    *,
    sample_rate: int = 48000,
    duck: bool = True,
    dialogue_gain_db: float | None = None,
) -> tuple[np.ndarray, dict]:
    """Mix background (stereo or mono) with the dialogue track."""
    bg = np.asarray(background, dtype=np.float32)
    if bg.ndim == 1:
        bg = bg[:, None]
    dlg = np.asarray(dialogue, dtype=np.float32).reshape(-1)
    length = max(bg.shape[0], dlg.size)
    if bg.shape[0] < length:
        bg = np.pad(bg, ((0, length - bg.shape[0]), (0, 0)))
    if dlg.size < length:
        dlg = np.pad(dlg, (0, length - dlg.size))
    if duck:
        env = duck_envelope(dlg, sample_rate=sample_rate)
        bg = bg * env[:, None]
    gain = dsp.db_to_linear(settings.dialogue_gain_db if dialogue_gain_db is None else dialogue_gain_db)
    mixed = bg + (dlg * gain)[:, None]
    # de-click the very first/last samples (inverse-STFT edges can pop)
    fade = int(0.01 * sample_rate)
    if mixed.shape[0] > 2 * fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        mixed[:fade] = mixed[:fade] * ramp
        mixed[-fade:] = mixed[-fade:] * ramp[::-1]
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    limiter_applied = False
    if peak > 0.98:
        mixed *= 0.98 / peak
        limiter_applied = True
    metrics = {
        "background_rms_db": round(dsp.rms_db(bg), 2),
        "dialogue_rms_db": round(dsp.rms_db(dlg), 2),
        "mix_peak": round(float(np.max(np.abs(mixed))) if mixed.size else 0.0, 4),
        "limiter_applied": limiter_applied,
        "duck_db": settings.background_duck_db if duck else 0.0,
    }
    return mixed.astype(np.float32), metrics


def write_mix(path: Path, mixed: np.ndarray, sample_rate: int) -> Path:
    channels = 2 if mixed.ndim > 1 and mixed.shape[1] > 1 else 1
    write_wav(path, mixed, sample_rate, channels=channels)
    return path
