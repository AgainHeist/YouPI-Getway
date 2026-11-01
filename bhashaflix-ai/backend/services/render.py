"""Final render: original video stream + new audio tracks, plus verification.

The video stream is *always* copied (`-c:v copy`).  We then fingerprint the
compressed video stream of input and output and store the result, so the UI can
state — with evidence — that the original picture was not re-encoded, cropped,
retimed or replaced.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from ..engines.media import MediaError, run_ffmpeg, silence_check, video_stream_md5
from .languages import get_language

log = logging.getLogger("bhashaflix.render")

LANG_ISO639_2 = {
    "hi": "hin", "en": "eng", "bho": "bho", "ur": "urd", "ta": "tam", "te": "tel",
    "bn": "ben", "mr": "mar", "pa": "pan", "gu": "guj", "ml": "mal", "kn": "kan",
    "es": "spa", "fr": "fra", "de": "deu", "ja": "jpn", "ko": "kor", "zh": "zho",
    "ar": "ara", "ru": "rus", "pt": "por", "id": "ind",
}


@dataclass
class RenderResult:
    dubbed_path: Path
    original_audio_path: Path
    mkv_path: Path | None
    subtitles: dict
    verification: dict
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dubbed_path": str(self.dubbed_path),
            "original_audio_path": str(self.original_audio_path),
            "mkv_path": str(self.mkv_path) if self.mkv_path else None,
            "subtitles": {k: str(v) for k, v in self.subtitles.items()},
            "verification": self.verification,
            "warnings": self.warnings,
        }


def _audio_lang(code: str) -> str:
    return LANG_ISO639_2.get(code, "und")


def render(
    *,
    source: Path,
    dubbed_audio: Path,
    out_dir: Path,
    target_lang: str,
    source_lang: str,
    audio_stream_index: int = 0,
    duration: float | None = None,
    subtitles: dict[str, Path] | None = None,
    video_stream_index: int = 0,
    bitrate: str = "192k",
) -> RenderResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    dubbed = out_dir / f"bhashaflix_{target_lang}.mp4"
    original_audio = out_dir / "bhashaflix_original_audio.mp4"

    common = ["-map", f"0:v:{video_stream_index}", "-c:v", "copy", "-movflags", "+faststart"]
    if duration:
        common += ["-t", f"{duration:.3f}"]

    # 1) Dubbed track first (it is what viewers get), original kept as track 2.
    run_ffmpeg([
        "-i", str(source), "-i", str(dubbed_audio),
        *common,
        "-map", "1:a:0",
        "-map", f"0:a:{audio_stream_index}",
        "-c:a", "aac", "-b:a", bitrate, "-ac", "2", "-ar", "48000",
        "-metadata:s:a:0", f"language={_audio_lang(target_lang)}",
        "-metadata:s:a:0", f"title=BhashaFlix AI {get_language(target_lang)['en'] if get_language(target_lang) else target_lang} dub",
        "-metadata:s:a:0", "comment=AI dubbed dialogue track",
        "-metadata:s:a:1", f"language={_audio_lang(source_lang)}",
        "-metadata:s:a:1", "title=Original audio",
        "-metadata", "comment=Video stream copied bit-exact from the original upload",
        str(dubbed),
    ])

    # 2) Same picture, original audio only — used by the player's track switch.
    run_ffmpeg([
        "-i", str(source),
        *common,
        "-map", f"0:a:{audio_stream_index}",
        "-c:a", "aac", "-b:a", bitrate, "-ac", "2", "-ar", "48000",
        "-metadata:s:a:0", f"language={_audio_lang(source_lang)}",
        "-metadata:s:a:0", "title=Original audio",
        str(original_audio),
    ])

    # 3) Optional MKV with soft subtitles (nice for archiving; not needed to play).
    mkv_path = None
    subtitle_paths = subtitles or {}
    if subtitle_paths:
        try:
            mkv = out_dir / f"bhashaflix_{target_lang}_multitrack.mkv"
            args = ["-i", str(source), "-i", str(dubbed_audio)]
            for path in subtitle_paths.values():
                args += ["-i", str(path)]
            args += [
                "-map", f"0:v:{video_stream_index}", "-c:v", "copy",
                "-map", "1:a:0", "-map", f"0:a:{audio_stream_index}",
                "-c:a", "aac", "-b:a", bitrate,
            ]
            for i, (key, _path) in enumerate(subtitle_paths.items()):
                args += ["-map", f"{2 + i}:s:0"]
                code = "eng" if key == "source" else _audio_lang(target_lang)
                args += ["-metadata:s:s:%d" % i, f"language={code}", "-metadata:s:s:%d" % i,
                         f"title={'Original dialogue' if key == 'source' else 'Translated dialogue'}"]
            args += ["-c:s", "srt", str(mkv)]
            run_ffmpeg(args)
            mkv_path = mkv
        except MediaError as exc:
            warnings.append(f"The multi-track MKV could not be written ({exc}). MP4 outputs are unaffected.")
            mkv_path = None

    # 4) Verification: the compressed video stream must be byte-identical.
    verification: dict = {"video_stream_copied": True}
    try:
        src_md5 = video_stream_md5(source, video_stream_index)
        out_md5 = video_stream_md5(dubbed, 0)
        verification.update(
            {
                "original_video_md5": src_md5,
                "rendered_video_md5": out_md5,
                "video_identical": src_md5 == out_md5,
            }
        )
        if src_md5 != out_md5:
            warnings.append(
                "Video fingerprint mismatch: the output picture differs from the upload. "
                "Do not publish this result."
            )
    except MediaError as exc:
        verification["video_identical"] = None
        warnings.append(f"Video fingerprint could not be computed: {exc}")

    # 5) Honest loudness check — never claim success for a silent dub.
    level = silence_check(dubbed)
    verification["audio_level"] = level
    if level.get("available") and not level.get("audible", True):
        raise MediaError(
            "The rendered file contains no audible dialogue. Check the generated voices and retry.",
            code="AUDIO_SYNC_FAILED",
        )

    return RenderResult(
        dubbed_path=dubbed,
        original_audio_path=original_audio,
        mkv_path=mkv_path,
        subtitles=subtitle_paths,
        verification=verification,
        warnings=warnings,
    )


def render_audio_only(*, dub_audio: Path, out_dir: Path, target_lang: str) -> Path:
    """Export the dubbed audio on its own (audio-only download)."""
    dest = out_dir / f"bhashaflix_{target_lang}_audio.m4a"
    run_ffmpeg(["-i", str(dub_audio), "-c:a", "aac", "-b:a", "192k", str(dest)])
    return dest
