"""Speech recognition engines.

Priority: faster-whisper -> openai-whisper -> vosk -> user-supplied subtitles.

If no model is installed we do NOT invent a transcript.  The job stops with
`ASR_UNAVAILABLE` and the UI offers the honest alternative: import subtitles
(or a transcript) that the user already owns.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..services.languages import detect_text_language

log = logging.getLogger("bhashaflix.asr")


@dataclass
class ASRResult:
    segments: list[dict]  # [{start, end, text, confidence}]
    language: str
    language_probability: float
    engine: str
    language_source: str  # "model" | "text-heuristic" | "user"


class ASRError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


class BaseASR:
    name = "base"
    model_id = ""
    supports_language_detection = False

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return False, "not implemented"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> ASRResult:
        raise NotImplementedError


class FasterWhisperASR(BaseASR):
    name = "faster-whisper"
    supports_language_detection = True

    def __init__(self, model: str | None = None, compute_type: str | None = None, device: str = "auto"):
        from faster_whisper import WhisperModel  # type: ignore

        self.model_id = model or settings.asr_model
        self.device = device
        if device == "auto":
            device = "cuda" if _cuda_available() else "cpu"
        self._device = device
        self.model = WhisperModel(
            self.model_id,
            device=device,
            compute_type=compute_type or settings.asr_compute_type,
        )

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False, "pip install faster-whisper (needs a model download on first run)"
        return True, "ready"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> ASRResult:
        lang_arg = None if (language or "auto") in {"auto", ""} else language
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            language=lang_arg,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        segments = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start": round(float(seg.start), 3),
                    "end": round(float(seg.end), 3),
                    "text": text,
                    "confidence": round(float(getattr(seg, "avg_logprob", 0.0) or 0.0), 3),
                }
            )
        prob = float(getattr(info, "language_probability", 0.0) or 0.0)
        return ASRResult(
            segments=segments,
            language=getattr(info, "language", lang_arg or "unknown") or "unknown",
            language_probability=round(prob, 3),
            engine=self.name,
            language_source="model",
        )


class OpenAIWhisperASR(BaseASR):
    name = "openai-whisper"
    supports_language_detection = True

    def __init__(self, model: str | None = None):
        import whisper  # type: ignore

        self.model_id = model or settings.asr_model
        self.model = whisper.load_model(self.model_id)

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import whisper  # noqa: F401
        except Exception:
            return False, "pip install openai-whisper"
        return True, "ready"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> ASRResult:
        lang_arg = None if (language or "auto") in {"auto", ""} else language
        result = self.model.transcribe(str(audio_path), language=lang_arg, verbose=False)
        segments = []
        for seg in result.get("segments", []):
            text = (seg.get("text") or "").strip()
            if text:
                segments.append(
                    {
                        "start": round(float(seg["start"]), 3),
                        "end": round(float(seg["end"]), 3),
                        "text": text,
                        "confidence": round(float(seg.get("avg_logprob", 0.0) or 0.0), 3),
                    }
                )
        return ASRResult(
            segments=segments,
            language=result.get("language", lang_arg or "unknown"),
            language_probability=None if lang_arg else 0.0,
            engine=self.name,
            language_source="model",
        )


class VoskASR(BaseASR):
    name = "vosk"

    def __init__(self, model_path: str | None = None):
        import json
        import os
        import wave

        from vosk import KaldiRecognizer, Model  # type: ignore

        self._json = json
        self._wave = wave
        path = model_path or os.environ.get("BFLIX_VOSK_MODEL", "")
        if not path or not Path(path).exists():
            raise ASRError(
                "ASR_UNAVAILABLE",
                "Vosk needs a local model directory (BFLIX_VOSK_MODEL).",
                "Download a model from alphacephei.com/vosk/models and point BFLIX_VOSK_MODEL at it.",
            )
        self.model_id = Path(path).name
        self.model = Model(path)
        self._KaldiRecognizer = KaldiRecognizer

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import vosk  # noqa: F401
        except Exception:
            return False, "pip install vosk (+ a local model directory)"
        return True, "ready"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> ASRResult:
        rec = self._KaldiRecognizer(self.model, 16000)
        rec.SetWords(True)
        with self._wave.open(str(audio_path), "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
        result = self._json.loads(rec.FinalResult())
        segments = []
        for word_group, text in _group_vosk_words(result.get("result", [])):
            if text:
                segments.append({"start": word_group[0], "end": word_group[1], "text": text, "confidence": None})
        full_text = " ".join(s["text"] for s in segments)
        lang, conf = detect_text_language(full_text)
        return ASRResult(
            segments=segments,
            language=lang,
            language_probability=conf,
            engine=self.name,
            language_source="text-heuristic",
        )


def _group_vosk_words(words: list[dict], max_gap: float = 0.6, max_len: float = 8.0):
    """Group word timings into subtitle-sized cues."""
    group: list[dict] = []
    for word in words:
        if group and (word["start"] - group[-1]["end"] > max_gap or word["end"] - group[0]["start"] > max_len):
            yield (round(group[0]["start"], 3), round(group[-1]["end"], 3)), " ".join(w["word"] for w in group)
            group = []
        group.append(word)
    if group:
        yield (round(group[0]["start"], 3), round(group[-1]["end"], 3)), " ".join(w["word"] for w in group)


class ScriptASR(BaseASR):
    """'User already has the dialogue' path.

    This is NOT speech recognition — it is the honest fallback used when no
    model is installed, or when the user prefers their own subtitle file.  The
    UI labels it "Imported subtitles" everywhere.
    """

    name = "imported-subtitles"

    def __init__(self, cues: list[dict]):
        self.cues = cues

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return True, "always available (requires a subtitle file)"

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> ASRResult:
        segments = [
            {
                "start": round(float(c["start"]), 3),
                "end": round(float(c["end"]), 3),
                "text": (c.get("text") or "").strip(),
                "confidence": None,
            }
            for c in self.cues
            if (c.get("text") or "").strip()
        ]
        lang = language if language and language != "auto" else None
        conf = 1.0
        source = "user"
        if not lang:
            lang, conf = detect_text_language(" ".join(s["text"] for s in segments))
            source = "text-heuristic"
        return ASRResult(
            segments=segments,
            language=lang or "unknown",
            language_probability=conf,
            engine=self.name,
            language_source=source,
        )


def _cuda_available() -> bool:
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def gpu_available() -> bool:
    return _cuda_available()


ASR_CLASSES: list[type[BaseASR]] = [FasterWhisperASR, OpenAIWhisperASR, VoskASR]


def available_asr() -> list[dict]:
    out = []
    for cls in ASR_CLASSES:
        ok, reason = cls.dependencies_ok()
        out.append({"engine": cls.name, "available": ok, "reason": reason})
    return out


def build_asr(engine: str | None = None, *, cues: list[dict] | None = None) -> BaseASR:
    """Instantiate the requested engine, or the first available one."""
    requested = (engine or settings.asr_engine or "auto").lower()
    if cues:
        return ScriptASR(cues)
    if requested in {"imported", "subtitles", "script", "imported-subtitles"}:
        if not cues:
            raise ASRError(
                "ASR_UNAVAILABLE",
                "Imported-subtitle mode needs a subtitle file.",
                "Attach an SRT/VTT file, or install a Whisper model for automatic transcription.",
            )
        return ScriptASR(cues)
    candidates = ASR_CLASSES if requested == "auto" else [c for c in ASR_CLASSES if c.name == requested]
    errors = []
    for cls in candidates:
        ok, reason = cls.dependencies_ok()
        if not ok:
            errors.append(f"{cls.name}: {reason}")
            continue
        try:
            return cls()
        except ASRError:
            raise
        except Exception as exc:  # model download / OOM / licence gate
            errors.append(f"{cls.name}: {type(exc).__name__}: {exc}")
            log.warning("ASR engine %s failed to load: %s", cls.name, exc)
    raise ASRError(
        "ASR_UNAVAILABLE",
        "No speech-recognition engine is available on this backend.",
        "Install one: `pip install faster-whisper` (recommended) then retry. "
        "Attempts: " + " | ".join(errors[:3]),
    )
