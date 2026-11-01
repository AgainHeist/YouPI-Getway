"""Subtitle parsing / writing (SRT, WebVTT) — no external deps."""
from __future__ import annotations

import re
from pathlib import Path

_TS = re.compile(
    r"(?P<h>\d{1,3}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})\s*-->\s*"
    r"(?P<h2>\d{1,3}):(?P<m2>\d{2}):(?P<s2>\d{2})[,.](?P<ms2>\d{1,3})"
)
_VTT_HEADER = re.compile(r"^WEBVTT", re.IGNORECASE)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_subtitles(text: str) -> list[dict]:
    """Parse SRT or WebVTT into [{start, end, text}] sorted by start time."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and _VTT_HEADER.search(lines[0]):
        lines = lines[1:]
    cues: list[dict] = []
    current: dict | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None:
            body = " ".join(x.strip() for x in buffer if x.strip())
            body = re.sub(r"<[^>]+>", "", body)
            body = re.sub(r"\{\\[^}]+\}", "", body)
            body = body.replace("\n", " ").strip()
            if body:
                current["text"] = body
                cues.append(current)
        current, buffer = None, []

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue
        match = _TS.search(line)
        if match:
            flush()
            current = {
                "start": _to_seconds(match["h"], match["m"], match["s"], match["ms"]),
                "end": _to_seconds(match["h2"], match["m2"], match["s2"], match["ms2"]),
                "text": "",
            }
            tail = line[match.end():].strip()
            if tail:
                buffer.append(tail)
            continue
        if line.isdigit() and current is None:
            continue  # cue index
        if current is not None:
            buffer.append(line)
    flush()
    cues.sort(key=lambda c: c["start"])
    # Repair inverted / zero-length cues.
    for cue in cues:
        if cue["end"] <= cue["start"]:
            cue["end"] = cue["start"] + 1.2
    return cues


def _fmt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[dict], translated: bool = False) -> str:
    out: list[str] = []
    for i, cue in enumerate(cues, start=1):
        text = cue.get("translated_text") if translated else cue.get("text")
        text = (text or cue.get("text") or "").strip()
        out.append(str(i))
        out.append(f"{_fmt(cue['start'])} --> {_fmt(cue['end'])}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def to_vtt(cues: list[dict], translated: bool = False) -> str:
    out = ["WEBVTT", ""]
    for i, cue in enumerate(cues, start=1):
        text = cue.get("translated_text") if translated else cue.get("text")
        text = (text or cue.get("text") or "").strip()
        out.append(str(i))
        out.append(f"{_fmt(cue['start']).replace(',', '.')} --> {_fmt(cue['end']).replace(',', '.')}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def write_srt(path: Path, cues: list[dict], translated: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_srt(cues, translated=translated), encoding="utf-8")
    return path


def read_subtitles(path: Path) -> list[dict]:
    return parse_subtitles(path.read_text(encoding="utf-8", errors="replace"))


def looks_like_subtitles(text: str) -> bool:
    return bool(_TS.search(text)) or bool(_VTT_HEADER.search(text.strip()[:64]))
