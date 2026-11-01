"""FFmpeg / FFprobe plumbing.

Everything that touches a media file goes through this module so that:
  * the binaries are resolved in exactly one place,
  * every subprocess has a timeout and a structured error,
  * probing works even when only PyAV (libav) is installed (no ffprobe binary).
"""
from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ffmpeg_executable, ffprobe_executable, settings

log = logging.getLogger("bhashaflix.media")


class MediaError(RuntimeError):
    """A media operation failed; message is safe to show to the user."""

    def __init__(self, message: str, code: str = "MEDIA_ERROR", hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


@dataclass
class StreamInfo:
    index: int
    kind: str  # video | audio | subtitle
    codec: str = ""
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    language: str | None = None
    title: str | None = None
    bit_rate: int | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class MediaInfo:
    path: str
    container: str
    duration: float
    size_bytes: int
    bit_rate: int | None
    streams: list[StreamInfo]
    probe_tool: str

    @property
    def video_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.kind == "video"]

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.kind == "audio"]

    @property
    def subtitle_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.kind == "subtitle"]

    def to_dict(self) -> dict:
        return {
            "container": self.container,
            "duration": round(self.duration, 3),
            "size_bytes": self.size_bytes,
            "bit_rate": self.bit_rate,
            "probe_tool": self.probe_tool,
            "video_streams": [s.to_dict() for s in self.video_streams],
            "audio_streams": [s.to_dict() for s in self.audio_streams],
            "subtitle_streams": [s.to_dict() for s in self.subtitle_streams],
        }


# --------------------------------------------------------------------------- #
# process helpers
# --------------------------------------------------------------------------- #
def ffmpeg() -> str:
    exe = ffmpeg_executable()
    if not exe:
        raise MediaError(
            "FFmpeg is not installed on the server.",
            code="FFMPEG_MISSING",
            hint="Install ffmpeg, set BFLIX_FFMPEG, or `pip install imageio-ffmpeg`.",
        )
    return exe


def run_ffmpeg(args: list[str], *, timeout: float | None = None, log_tail: int = 24) -> str:
    """Run ffmpeg with -hide_banner -nostdin and return stderr text."""
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", *args]
    log.debug("ffmpeg %s", " ".join(shlex.quote(a) for a in cmd[1:]))
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout or settings.job_timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - environment dependent
        raise MediaError(
            "FFmpeg timed out while processing the media.",
            code="PROCESSING_TIMEOUT",
            hint="Try a shorter clip or raise BFLIX_JOB_TIMEOUT_SEC.",
        ) from exc
    stderr = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-log_tail:])
        raise MediaError(
            f"FFmpeg failed (exit {proc.returncode}).\n{tail}",
            code="FFMPEG_FAILED",
        )
    return stderr


# --------------------------------------------------------------------------- #
# probing
# --------------------------------------------------------------------------- #
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: (Video|Audio|Subtitle): (\w+)")


def _parse_fps(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            n, d = float(num), float(den)
            return round(n / d, 4) if d else None
        except ValueError:
            return None
    try:
        return round(float(value), 4)
    except ValueError:
        return None


def probe_with_ffprobe(path: Path) -> MediaInfo:
    exe = ffprobe_executable()
    assert exe
    cmd = [
        exe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise MediaError(
            "The file could not be read as a media file (it may be corrupt or not a video).",
            code="CORRUPT_MEDIA",
        )
    data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    fmt = data.get("format", {})
    streams: list[StreamInfo] = []
    for s in data.get("streams", []):
        kind = s.get("codec_type", "")
        if kind not in {"video", "audio", "subtitle"}:
            continue
        tags = s.get("tags") or {}
        streams.append(
            StreamInfo(
                index=int(s.get("index", 0)),
                kind=kind,
                codec=s.get("codec_name", ""),
                duration=float(s["duration"]) if s.get("duration") else None,
                width=s.get("width"),
                height=s.get("height"),
                fps=_parse_fps(s.get("avg_frame_rate") or s.get("r_frame_rate")),
                sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
                channels=s.get("channels"),
                language=tags.get("language"),
                title=tags.get("title"),
                bit_rate=int(s["bit_rate"]) if s.get("bit_rate") else None,
                extra={k: v for k, v in s.items() if k in {"disposition", "pix_fmt", "profile"}},
            )
        )
    duration = float(fmt.get("duration") or 0.0)
    return MediaInfo(
        path=str(path),
        container=(fmt.get("format_name") or path.suffix.lstrip(".")),
        duration=duration,
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        streams=streams,
        probe_tool="ffprobe",
    )


def _parse_ffmpeg_info(stderr: str, path: Path) -> MediaInfo:
    """Last-resort parser for `ffmpeg -i` output (used when ffprobe is absent
    and PyAV is unavailable)."""
    duration = 0.0
    m = _DUR_RE.search(stderr)
    if m:
        h, mi, se = m.groups()
        duration = int(h) * 3600 + int(mi) * 60 + float(se)
    streams: list[StreamInfo] = []
    idx = 0
    for line in stderr.splitlines():
        sm = _STREAM_RE.search(line)
        if not sm:
            continue
        kind = sm.group(1).lower()
        codec = sm.group(2)
        fps_m = _FPS_RE.search(line)
        streams.append(
            StreamInfo(
                index=idx,
                kind=kind,
                codec=codec,
                fps=float(fps_m.group(1)) if fps_m and kind == "video" else None,
            )
        )
        idx += 1
    return MediaInfo(
        path=str(path),
        container=path.suffix.lstrip(".") or "unknown",
        duration=duration,
        size_bytes=path.stat().st_size,
        bit_rate=None,
        streams=streams,
        probe_tool="ffmpeg-stderr",
    )


def probe_with_pyav(path: Path) -> MediaInfo:
    try:
        import av  # type: ignore
    except Exception as exc:  # pragma: no cover - optional
        raise MediaError(
            "Media probing unavailable on this server (no ffprobe / PyAV).",
            code="PROBE_UNAVAILABLE",
            hint="Install ffmpeg (includes ffprobe) or `pip install av`.",
        ) from exc
    try:
        with av.open(str(path)) as container:
            duration = float(container.duration / 1_000_000) if container.duration else 0.0
            streams: list[StreamInfo] = []
            for s in container.streams:
                kind = s.type
                if kind not in {"video", "audio", "subtitle"}:
                    continue
                ctx = s.codec_context
                fps = None
                try:
                    if s.average_rate:
                        fps = round(float(s.average_rate), 4)
                except Exception:
                    fps = None
                lang = (s.metadata or {}).get("language")
                streams.append(
                    StreamInfo(
                        index=s.index,
                        kind=kind,
                        codec=getattr(ctx, "name", "") or "",
                        duration=float(s.duration * s.time_base) if s.duration and s.time_base else None,
                        width=getattr(ctx, "width", None),
                        height=getattr(ctx, "height", None),
                        fps=fps,
                        sample_rate=getattr(ctx, "sample_rate", None),
                        channels=getattr(ctx, "channels", None),
                        language=lang,
                        title=(s.metadata or {}).get("title"),
                        bit_rate=getattr(ctx, "bit_rate", None),
                    )
                )
            container_name = (container.format.name or path.suffix.lstrip(".")).split(",")[0]
            if duration <= 0:
                durations = [s.duration * s.time_base for s in container.streams if s.duration and s.time_base]
                duration = float(max(durations)) if durations else 0.0
            return MediaInfo(
                path=str(path),
                container=container_name,
                duration=duration,
                size_bytes=path.stat().st_size,
                bit_rate=None,
                streams=streams,
                probe_tool="pyav",
            )
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(
            "The file could not be read as a media file (it may be corrupt or not a video).",
            code="CORRUPT_MEDIA",
        ) from exc


def probe(path: Path) -> MediaInfo:
    """Probe a media file: ffprobe -> PyAV -> ffmpeg stderr."""
    if not path.exists():
        raise MediaError("File not found.", code="FILE_NOT_FOUND")
    if ffprobe_executable():
        try:
            return probe_with_ffprobe(path)
        except MediaError:
            raise
        except Exception:  # pragma: no cover
            log.exception("ffprobe failed, falling back")
    try:
        return probe_with_pyav(path)
    except MediaError:
        if ffmpeg_executable():
            cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path)]
            proc = subprocess.run(cmd, capture_output=True, timeout=120)
            info = _parse_ffmpeg_info(proc.stderr.decode("utf-8", "replace"), path)
            if info.streams:
                return info
        raise


# --------------------------------------------------------------------------- #
# audio / video primitives
# --------------------------------------------------------------------------- #
def extract_audio(
    src: Path,
    dest: Path,
    *,
    stream_index: int | None = None,
    sample_rate: int = 48000,
    channels: int = 2,
    codec: str = "pcm_s16le",
) -> Path:
    args = ["-i", str(src)]
    if stream_index is not None:
        args += ["-map", f"0:a:{stream_index}" if stream_index < 32 else "0:a:0"]
    else:
        args += ["-map", "0:a:0"]
    args += ["-vn", "-sn", "-dn", "-ac", str(channels), "-ar", str(sample_rate), "-c:a", codec, str(dest)]
    run_ffmpeg(args)
    if not dest.exists() or dest.stat().st_size < 100:
        raise MediaError("Audio extraction produced an empty file.", code="AUDIO_EXTRACTION_FAILED")
    return dest


def decode_to_numpy(path: Path, *, channels: int | None = None, sample_rate: int | None = None):
    """Decode an audio file into float32 numpy arrays.

    Returns (samples[frames, channels] as float32 in [-1, 1], sample_rate).

    PyAV is used when it is installed; otherwise we pipe the file through the
    FFmpeg binary (`-f f32le`).  The fallback matters on phones/Termux and slim
    images where building PyAV is not practical but ffmpeg is a system package.

    Note: libswresample in some PyAV builds produces garbage when it is asked
    to change the channel layout of a stream, so we always resample *keeping*
    the native layout and do the mono/stereo conversion ourselves in numpy.
    """
    target_channels = channels or 2
    target_rate = sample_rate or 48000
    try:
        import av  # type: ignore  # noqa: F401
    except Exception:
        return _decode_via_ffmpeg(path, target_channels, target_rate)
    import numpy as np
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        native_layout = stream.codec_context.layout.name
        native_channels = stream.codec_context.layout.nb_channels or 1
        rate = stream.codec_context.sample_rate or target_rate
        resampler = None
        if rate != target_rate:
            resampler = av.AudioResampler(format="fltp", layout=native_layout, rate=target_rate)
        for frame in container.decode(stream):
            frames = resampler.resample(frame) if resampler else [frame]
            for out in frames:
                chunks.append(_frame_to_float(out))
        if resampler is not None:
            try:
                for out in resampler.resample(None):
                    chunks.append(_frame_to_float(out))
            except Exception:  # pragma: no cover
                pass
    if not chunks:
        return np.zeros((0, target_channels), dtype=np.float32), target_rate
    data = np.concatenate(chunks, axis=0).astype(np.float32, copy=False)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] != target_channels:
        if target_channels == 1:
            data = data.mean(axis=1, keepdims=True)
        elif data.shape[1] == 1:
            data = np.repeat(data, target_channels, axis=1)
        else:
            data = data[:, :target_channels]
    return data, target_rate


def _decode_via_ffmpeg(path: Path, channels: int, sample_rate: int):
    """Decode with the ffmpeg binary when PyAV is unavailable (no wheel/compiler)."""
    import numpy as np

    exe = ffmpeg_executable()
    if not exe:
        raise MediaError(
            "No audio decoder available: PyAV is not installed and FFmpeg was not found.",
            code="DECODER_MISSING",
            hint="Install ffmpeg (`pkg install ffmpeg` on Termux) or `pip install av`.",
        )
    cmd = [
        exe, "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(path),
        "-vn", "-sn", "-dn",
        "-ac", str(channels), "-ar", str(sample_rate),
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=900)
    if proc.returncode != 0:
        raise MediaError(
            "FFmpeg could not decode this audio stream.",
            code="AUDIO_DECODE_FAILED",
            hint=proc.stderr.decode("utf-8", "replace")[-600:],
        )
    data = np.frombuffer(proc.stdout, dtype="<f4")
    usable = data.size - (data.size % channels)
    data = data[:usable].reshape(-1, channels).astype(np.float32, copy=False)
    if data.size == 0:
        raise MediaError("Decoded audio was empty.", code="AUDIO_DECODE_FAILED")
    return data, sample_rate


def _frame_to_float(frame) -> "np.ndarray":
    """AudioFrame -> (frames, channels) float32 in [-1, 1]."""
    import numpy as np

    arr = frame.to_ndarray()
    dtype = arr.dtype
    if dtype == np.int16:
        arr = arr.astype(np.float32) / 32768.0
    elif dtype == np.int32:
        arr = arr.astype(np.float32) / 2147483648.0
    elif dtype == np.uint8:
        arr = (arr.astype(np.float32) - 128.0) / 128.0
    else:
        arr = arr.astype(np.float32)
    # planar (channels, frames) vs packed (1, frames*channels)
    channels = frame.layout.nb_channels or 1
    if arr.ndim == 2:
        if arr.shape[0] == channels and channels > 1:
            return arr.T.copy()
        if arr.shape[0] == 1 and channels > 1 and arr.shape[1] % channels == 0:
            return arr.reshape(-1, channels).copy()
        if arr.shape[1] == channels:
            return arr.copy()
        return arr.T.copy()
    return arr.reshape(-1, 1)


def write_wav(path: Path, samples, sample_rate: int, channels: int | None = None) -> Path:
    """Write float32 numpy audio to 16-bit PCM WAV (no external deps)."""
    import struct

    import numpy as np

    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    channels = channels or arr.shape[1]
    clipped = np.clip(arr, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,                      # PCM
        channels,
        sample_rate,
        sample_rate * channels * 2,
        channels * 2,
        16,
        b"data",
        data_size,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(pcm)
    return path


def audio_duration(path: Path) -> float:
    try:
        info = probe(path)
        return info.duration
    except MediaError:
        return 0.0


def change_tempo(src: Path, dest: Path, tempo: float, *, sample_rate: int = 48000, channels: int = 1) -> Path:
    """Time-stretch without changing pitch using ffmpeg's atempo (chained)."""
    tempo = max(0.5, min(2.0, float(tempo)))
    filters: list[str] = []
    remaining = tempo
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    args = [
        "-i", str(src), "-vn", "-map", "0:a:0",
        "-af", ",".join(filters),
        "-ac", str(channels), "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dest),
    ]
    run_ffmpeg(args)
    return dest


def convert_audio(src: Path, dest: Path, *, sample_rate: int = 48000, channels: int = 1) -> Path:
    args = [
        "-i", str(src), "-vn", "-map", "0:a:0",
        "-ac", str(channels), "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dest),
    ]
    run_ffmpeg(args)
    return dest


def video_stream_md5(path: Path, stream_index: int = 0) -> str:
    """Bit-exact fingerprint of the *compressed* video stream.

    Because the renderer copies the stream (`-c:v copy`), this value must match
    the original file exactly.  It is the machine-checkable proof that no
    original frame was re-encoded, cropped, retimed or replaced.
    """
    exe = ffmpeg_executable()
    if not exe:
        raise MediaError("FFmpeg unavailable for verification.", code="FFMPEG_MISSING")
    cmd = [
        exe, "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(path), "-map", f"0:v:{stream_index}", "-c", "copy", "-f", "md5", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=1800)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or "MD5=" not in out:
        raise MediaError(
            "Could not compute the video fingerprint.",
            code="FINGERPRINT_FAILED",
        )
    return out.split("MD5=")[-1].strip()


def silence_check(path: Path, *, threshold_db: float = -50.0) -> dict:
    """Measure whether a rendered audio file actually contains sound.

    Uses ffmpeg's volumedetect.  Returns mean/max volume in dB.
    """
    exe = ffmpeg_executable()
    if not exe:
        return {"available": False}
    cmd = [
        exe, "-hide_banner", "-nostdin", "-i", str(path),
        "-vn", "-af", "volumedetect", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=900)
    text = proc.stderr.decode("utf-8", "replace")
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", text)
    peak = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", text)
    mean_db = float(mean.group(1)) if mean else None
    peak_db = float(peak.group(1)) if peak else None
    return {
        "available": True,
        "mean_db": mean_db,
        "peak_db": peak_db,
        "audible": (peak_db is not None and peak_db > threshold_db),
    }


def temp_path(suffix: str = ".wav") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix, dir=str(settings.tmp_dir))
    import os

    os.close(fd)
    Path(name).unlink(missing_ok=True)
    return Path(name)
