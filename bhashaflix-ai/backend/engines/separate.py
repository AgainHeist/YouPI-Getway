"""Dialogue / background separation.

Priority: Demucs (htdemucs, GPU-friendly, best quality) -> stereo centre
suppression (classical DSP, works when dialogue is centre-panned) -> ducking
(no separation; the original mix is kept and simply lowered under the new
dialogue).

Every result carries an honest `quality` note — the UI shows it instead of
pretending the separation is perfect.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..config import settings
from . import dsp
from .media import MediaError, convert_audio, decode_to_numpy, write_wav

log = logging.getLogger("bhashaflix.separate")


@dataclass
class SeparationResult:
    background_path: Path
    engine: str
    quality: str            # "high" | "medium" | "fallback"
    dialogue_removed: bool
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "quality": self.quality,
            "dialogue_removed": self.dialogue_removed,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


class BaseSeparator:
    name = "base"
    quality = "medium"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return False, "not implemented"

    def run(self, source_wav: Path, work_dir: Path, *, mono_source: bool = False) -> SeparationResult:
        raise NotImplementedError


class DemucsSeparator(BaseSeparator):
    name = "demucs"
    quality = "high"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
            import demucs  # noqa: F401
        except Exception:
            return False, "pip install demucs torch (+ ~300 MB weights on first run)"
        return True, "ready"

    def run(self, source_wav: Path, work_dir: Path, *, mono_source: bool = False) -> SeparationResult:
        out_dir = work_dir / "demucs"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, "-m", "demucs.separate",
            "--two-stems", "vocals",
            "-n", settings.demucs_model,
            "-o", str(out_dir),
            str(source_wav),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=settings.job_timeout_sec)
        if proc.returncode != 0:
            raise MediaError(
                "Demucs separation failed: " + proc.stderr.decode("utf-8", "replace")[-400:],
                code="RENDER_FAILED",
            )
        candidates = list(out_dir.rglob("no_vocals.*"))
        if not candidates:
            raise MediaError("Demucs produced no background stem.", code="RENDER_FAILED")
        background = work_dir / "background.wav"
        convert_audio(candidates[0], background, sample_rate=settings.work_sample_rate, channels=2)
        return SeparationResult(
            background_path=background,
            engine=self.name,
            quality="high",
            dialogue_removed=True,
            warnings=[
                "Background music and effects come from Demucs' instrumental stem. "
                "Faint dialogue bleed can remain in dense mixes.",
            ],
        )


class CenterSuppressionSeparator(BaseSeparator):
    """Spectral centre-channel extraction.

    Dialogue in a normal stereo film mix sits in the phantom centre, so
    L ≈ R for those bins.  We estimate the centre component per bin and
    subtract it, keeping everything that is panned or wide (music, ambience,
    effects).
    """

    name = "center-suppression"
    quality = "medium"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import numpy  # noqa: F401
            import av  # noqa: F401
        except Exception:
            return False, "needs numpy + audio decoding (PyAV or system ffmpeg)"
        return True, "ready"

    def run(self, source_wav: Path, work_dir: Path, *, mono_source: bool = False) -> SeparationResult:
        audio, rate = decode_to_numpy(source_wav, channels=2, sample_rate=settings.work_sample_rate)
        if mono_source or audio.shape[1] < 2:
            return self._mono_fallback(source_wav, work_dir)
        left = audio[:, 0]
        right = audio[:, 1]
        n_fft, hop = 2048, 512
        spec_l = dsp.stft(left, n_fft, hop)
        spec_r = dsp.stft(right, n_fft, hop)
        mid = (spec_l + spec_r) / 2.0
        side = (spec_l - spec_r) / 2.0
        mag_mid = np.abs(mid)
        mag_side = np.abs(side)
        # coherence: 1 when the bin is dead-centre, 0 when fully panned
        weight = np.clip(1.0 - (mag_side / (mag_mid + 1e-8)), 0.0, 1.0)
        # Only suppress bins that plausibly carry speech energy; a floor keeps
        # us from gutting quiet centre music completely.
        floor = 0.15
        weight = np.clip((weight - floor) / (1.0 - floor), 0.0, 1.0)
        center = mid * weight
        bg_l = spec_l - center
        bg_r = spec_r - center
        bg = np.stack(
            [
                dsp.istft(bg_l, n_fft, hop, length=len(left)),
                dsp.istft(bg_r, n_fft, hop, length=len(right)),
            ],
            axis=1,
        )
        removed_energy = float(np.mean(np.abs(center) ** 2))
        total_energy = float(np.mean(np.abs(mid) ** 2)) or 1e-9
        ratio = removed_energy / total_energy
        # Avoid a hollow result: if we removed almost everything, keep more mix.
        if ratio > 0.92:
            bg = bg * 0.5 + audio * 0.5
            ratio = 0.5
        np.clip(bg, -1.0, 1.0, out=bg)
        background = work_dir / "background.wav"
        write_wav(background, bg, rate, channels=2)
        warnings = [
            "Dialogue was suppressed with stereo centre extraction (no neural separator installed). "
            "Centre-panned music and bass lose some energy, and music mixed in mono can be affected.",
        ]
        return SeparationResult(
            background_path=background,
            engine=self.name,
            quality="medium",
            dialogue_removed=True,
            warnings=warnings,
            metrics={"center_energy_ratio": round(ratio, 3)},
        )

    def _mono_fallback(self, source_wav: Path, work_dir: Path) -> SeparationResult:
        background = work_dir / "background.wav"
        convert_audio(source_wav, background, sample_rate=settings.work_sample_rate, channels=2)
        return SeparationResult(
            background_path=background,
            engine="ducking",
            quality="fallback",
            dialogue_removed=False,
            warnings=[
                "The source audio is mono, so dialogue cannot be separated from music. "
                "The original mix is kept and automatically lowered under the new dialogue — "
                "the old voice will still be faintly audible. Supply a stereo source for a cleaner dub.",
            ],
            metrics={"mono_source": True},
        )


class DuckingSeparator(BaseSeparator):
    name = "ducking"
    quality = "fallback"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return True, "always available (no separation)"

    def run(self, source_wav: Path, work_dir: Path, *, mono_source: bool = False) -> SeparationResult:
        background = work_dir / "background.wav"
        convert_audio(source_wav, background, sample_rate=settings.work_sample_rate, channels=2)
        return SeparationResult(
            background_path=background,
            engine=self.name,
            quality="fallback",
            dialogue_removed=False,
            warnings=[
                "Audio separation was disabled: the original mix is preserved and ducked under the dub, "
                "so the original dialogue remains quietly audible.",
            ],
        )


def available_separators() -> list[dict]:
    out = []
    for cls in (DemucsSeparator, CenterSuppressionSeparator, DuckingSeparator):
        ok, reason = cls.dependencies_ok()
        out.append({"engine": cls.name, "available": ok, "quality": cls.quality, "reason": reason})
    return out


def build_separator(engine: str | None = None) -> BaseSeparator | None:
    requested = (engine or settings.separate_engine or "auto").lower()
    if requested in {"none", "off", "ducking"}:
        return DuckingSeparator()
    mapping = {cls.name: cls for cls in (DemucsSeparator, CenterSuppressionSeparator, DuckingSeparator)}
    candidates = [mapping[requested]] if requested in mapping else [DemucsSeparator, CenterSuppressionSeparator, DuckingSeparator]
    for cls in candidates:
        ok, _ = cls.dependencies_ok()
        if ok:
            return cls()
    return None
