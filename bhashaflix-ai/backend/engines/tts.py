"""Text-to-speech engines.

Priority: XTTS-v2 (multilingual, emotional) -> Piper (fast, per-language ONNX
voices) -> eSpeak NG (offline fallback that ships with this project and needs no
model download; robotic but genuinely intelligible in Indic languages).

Voice cloning of a real actor is OFF by default and requires an explicit
consent flag plus a reference clip the user is allowed to use
(BFLIX_ALLOW_VOICE_CLONING=1).  BhashaFlix never impersonates a performer by
default.
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..services.languages import get_language

log = logging.getLogger("bhashaflix.tts")


class TTSError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


@dataclass
class Voice:
    id: str            # engine-scoped id, e.g. "espeak:hi+f3"
    engine: str
    lang: str
    label: str
    gender: str        # male | female | neutral
    sample_rate: int
    quality: str       # "studio" | "good" | "robotic"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "engine": self.engine,
            "lang": self.lang,
            "label": self.label,
            "gender": self.gender,
            "sample_rate": self.sample_rate,
            "quality": self.quality,
        }


class BaseTTS:
    name = "base"
    quality = "good"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return False, "not implemented"

    def voices(self, lang: str) -> list[Voice]:
        raise NotImplementedError

    def synthesize(self, text: str, lang: str, voice_id: str, out_path: Path) -> Path:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# eSpeak NG (bundled lib, no model download)
# --------------------------------------------------------------------------- #
class EspeakTTS(BaseTTS):
    name = "espeak-ng"
    quality = "robotic"
    _lock = threading.Lock()
    _lib = None
    _rate = 22050
    _buffer: bytearray | None = None

    VARIANT_GENDERS = {
        "m1": "male", "m2": "male", "m3": "male", "m4": "male", "m5": "male",
        "m6": "male", "m7": "male",
        "f1": "female", "f2": "female", "f3": "female", "f4": "female", "f5": "female",
    }
    # Two clearly different timbres per language is enough for dialogue.
    DEFAULT_VARIANTS = ["m3", "f3", "m1", "f1", "m5", "f2"]

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import espeakng_loader  # noqa: F401
        except Exception:
            return False, "pip install espeakng-loader (bundles libespeak-ng + voices)"
        return True, "ready"

    @classmethod
    def _load(cls):
        if cls._lib is not None:
            return cls._lib
        import espeakng_loader

        lib = ctypes.CDLL(str(espeakng_loader.get_library_path()))
        lib.espeak_Initialize.restype = ctypes.c_int
        lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        cls._rate = lib.espeak_Initialize(2, 0, str(espeakng_loader.get_data_path()).encode(), 0)
        cb_type = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p
        )

        def _callback(wav, count, events):  # noqa: ANN001
            target = EspeakTTS._buffer
            if target is not None and count > 0:
                target.extend(ctypes.string_at(wav, count * 2))
            return 0

        cls._callback_ref = cb_type(_callback)  # keep a reference alive
        lib.espeak_SetSynthCallback(cls._callback_ref)
        lib.espeak_Synth.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint,
            ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
        ]
        lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        cls._lib = lib
        return lib

    @classmethod
    def supported(cls, lang: str) -> bool:
        entry = get_language(lang)
        return bool(entry and entry.get("espeak"))

    def voices(self, lang: str) -> list[Voice]:
        entry = get_language(lang)
        if not entry or not entry.get("espeak"):
            return []
        base = entry["espeak"]
        out = []
        for variant in self.DEFAULT_VARIANTS:
            gender = self.VARIANT_GENDERS.get(variant, "neutral")
            out.append(
                Voice(
                    id=f"espeak:{base}+{variant}",
                    engine=self.name,
                    lang=lang,
                    label=f"{entry['en']} — {'male' if gender == 'male' else 'female'} {variant[-1]}",
                    gender=gender,
                    sample_rate=22050,
                    quality=self.quality,
                )
            )
        return out

    def synthesize(self, text: str, lang: str, voice_id: str, out_path: Path) -> Path:
        entry = get_language(lang)
        if not entry or not entry.get("espeak"):
            raise TTSError(
                "TTS_UNAVAILABLE",
                f"eSpeak NG has no voice for '{entry['en'] if entry else lang}'.",
                "Install a Piper or XTTS voice for this language.",
            )
        voice_name = voice_id.split(":", 1)[1] if ":" in voice_id else f"{entry['espeak']}+m3"
        lib = self._load()
        import wave

        with self._lock:
            EspeakTTS._buffer = bytearray()
            rc = lib.espeak_SetVoiceByName(voice_name.encode())
            if rc != 0:
                # fall back to the plain language voice
                rc = lib.espeak_SetVoiceByName(entry["espeak"].encode())
                if rc != 0:
                    raise TTSError("TTS_UNAVAILABLE", f"eSpeak NG rejected voice '{voice_name}'.")
            lib.espeak_SetParameter(1, 165, 0)  # espeakRATE = words per minute
            lib.espeak_Synth(text.encode("utf-8"), 0, 0, 1, 0, 0, None)
            pcm = bytes(EspeakTTS._buffer or b"")
            EspeakTTS._buffer = None
        if len(pcm) < 400:
            raise TTSError("TTS_FAILED", "eSpeak NG produced no audio for this line.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._rate)
            wf.writeframes(pcm)
        return out_path


# --------------------------------------------------------------------------- #
# Piper (local ONNX voices)
# --------------------------------------------------------------------------- #
class PiperTTS(BaseTTS):
    name = "piper"
    quality = "good"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        exe = _find_piper()
        if not exe:
            return False, "pip install piper-tts (+ voice .onnx files in BFLIX_PIPER_VOICES_DIR)"
        if not any(settings.piper_voices_dir.glob("*.onnx")):
            return False, f"no voices found in {settings.piper_voices_dir}"
        return True, "ready"

    def voices(self, lang: str) -> list[Voice]:
        out = []
        for model in sorted(settings.piper_voices_dir.glob("*.onnx")):
            code = _piper_lang(model)
            if code != lang:
                continue
            gender = "female" if any(tag in model.name.lower() for tag in ("female", "f_", "_f")) else "male"
            out.append(
                Voice(
                    id=f"piper:{model.name}",
                    engine=self.name,
                    lang=lang,
                    label=f"{model.stem.replace('_', ' ')}",
                    gender=gender,
                    sample_rate=_piper_sample_rate(model),
                    quality="good",
                )
            )
        return out

    def synthesize(self, text: str, lang: str, voice_id: str, out_path: Path) -> Path:
        exe = _find_piper()
        if not exe:
            raise TTSError("TTS_UNAVAILABLE", "Piper is not installed.")
        model_name = voice_id.split(":", 1)[1] if ":" in voice_id else ""
        model = settings.piper_voices_dir / model_name
        if not model.exists():
            raise TTSError("TTS_UNAVAILABLE", f"Piper voice '{model_name}' is missing.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [exe, "--model", str(model), "--output_file", str(out_path)],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=180,
        )
        if proc.returncode != 0 or not out_path.exists():
            raise TTSError("TTS_FAILED", f"Piper failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
        return out_path


def _find_piper() -> str | None:
    from shutil import which

    for candidate in (os.environ.get("BFLIX_PIPER_BIN", ""), which("piper"), which("piper-tts")):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _piper_lang(model: Path) -> str:
    stem = model.stem.lower()
    for part in stem.replace("-", "_").split("_"):
        if len(part) == 2 and part.isalpha():
            return part
    return stem[:2]


def _piper_sample_rate(model: Path) -> int:
    card = model.with_suffix(".onnx.json")
    if card.exists():
        try:
            import json

            return int(json.loads(card.read_text()).get("audio", {}).get("sample_rate", 22050))
        except Exception:
            pass
    return 22050


# --------------------------------------------------------------------------- #
# XTTS-v2 (Coqui)
# --------------------------------------------------------------------------- #
class XttsTTS(BaseTTS):
    name = "xtts"
    quality = "studio"
    SUPPORTED = {"en", "hi", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh", "ja", "ko", "hu"}

    def __init__(self):
        if os.environ.get("COQUI_TOS_AGREED") != "1":
            raise TTSError(
                "TTS_UNAVAILABLE",
                "XTTS-v2 needs the Coqui Public Model License to be accepted.",
                "Read the CPML, then set COQUI_TOS_AGREED=1. The licence is non-commercial; "
                "check it before any paid use.",
            )
        from TTS.api import TTS  # type: ignore

        self.tts = TTS(settings.xtts_model)
        self._speakers: list[str] = []
        try:
            self._speakers = list(self.tts.speakers or [])
        except Exception:
            self._speakers = []

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import TTS  # noqa: F401
        except Exception:
            return False, "pip install coqui-tts (+ COQUI_TOS_AGREED=1)"
        return True, "ready"

    def voices(self, lang: str) -> list[Voice]:
        if lang not in self.SUPPORTED:
            return []
        speakers = self._speakers or ["Claribel Dervla", "Damien Black", "Ana Florence", "Andrew Chipper"]
        out = []
        for i, speaker in enumerate(speakers[:8]):
            female = i % 2 == 0
            out.append(
                Voice(
                    id=f"xtts:{speaker}",
                    engine=self.name,
                    lang=lang,
                    label=speaker,
                    gender="female" if female else "male",
                    sample_rate=24000,
                    quality=self.quality,
                )
            )
        return out

    def synthesize(self, text: str, lang: str, voice_id: str, out_path: Path) -> Path:
        if lang not in self.SUPPORTED:
            raise TTSError("UNSUPPORTED_LANGUAGE", f"XTTS-v2 does not support '{lang}'.")
        speaker = voice_id.split(":", 1)[1] if ":" in voice_id else (self._speakers or ["Claribel Dervla"])[0]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.tts.tts_to_file(
            text=text,
            language=lang,
            speaker=speaker,
            file_path=str(out_path),
            split_sentences=False,
        )
        return out_path


TTS_CLASSES = [XttsTTS, PiperTTS, EspeakTTS]


def available_tts() -> list[dict]:
    out = []
    for cls in TTS_CLASSES:
        ok, reason = cls.dependencies_ok()
        out.append({"engine": cls.name, "available": ok, "quality": cls.quality, "reason": reason})
    return out


_registry: dict[str, BaseTTS] = {}


def build_tts(engine: str | None = None) -> BaseTTS:
    requested = (engine or settings.tts_engine or "auto").lower()
    aliases = {"espeak": "espeak-ng", "espeakng": "espeak-ng", "xtts-v2": "xtts", "coqui": "xtts"}
    requested = aliases.get(requested, requested)
    mapping = {cls.name: cls for cls in TTS_CLASSES}
    candidates = [mapping[requested]] if requested in mapping else list(TTS_CLASSES)
    errors: list[str] = []
    for cls in candidates:
        if cls.name in _registry:
            return _registry[cls.name]
        ok, reason = cls.dependencies_ok()
        if not ok:
            errors.append(f"{cls.name}: {reason}")
            continue
        try:
            instance = cls()
        except Exception as exc:
            errors.append(f"{cls.name}: {exc}")
            continue
        _registry[cls.name] = instance
        return instance
    raise TTSError(
        "TTS_UNAVAILABLE",
        "No text-to-speech engine is available on this backend.",
        "Install one: `pip install espeakng-loader` (free, offline) or `pip install piper-tts` / "
        "`pip install coqui-tts` with COQUI_TOS_AGREED=1. Checked: " + " | ".join(errors[:3]),
    )


def voice_catalog(langs: list[str] | None = None, *, engine: str | None = None) -> dict:
    """All voices we can actually offer right now, grouped by language."""
    catalog: dict[str, list[dict]] = {}
    engines_ok: list[str] = []
    for cls in TTS_CLASSES:
        ok, _ = cls.dependencies_ok()
        if not ok:
            continue
        try:
            instance = build_tts(cls.name)
        except Exception:
            continue
        engines_ok.append(cls.name)
        target_langs = langs or [lang["code"] for lang in _all_langs()]
        for code in target_langs:
            try:
                voices = instance.voices(code)
            except Exception:
                voices = []
            if voices:
                catalog.setdefault(code, [])
                catalog[code].extend(v.to_dict() for v in voices)
    return {"languages": catalog, "engines": engines_ok}


def _all_langs():
    from ..services.languages import LANGUAGES

    return LANGUAGES


def default_voice_for(lang: str, gender: str = "unknown", *, index: int = 0, engine: str | None = None) -> str:
    """Pick a stable voice id for a speaker."""
    tts = build_tts(engine)
    voices = tts.voices(lang)
    if not voices:
        # try the next engine that has this language
        for cls in TTS_CLASSES:
            ok, _ = cls.dependencies_ok()
            if not ok:
                continue
            try:
                alt = build_tts(cls.name).voices(lang)
            except Exception:
                continue
            if alt:
                voices = alt
                break
    if not voices:
        raise TTSError(
            "TTS_UNAVAILABLE",
            f"No installed TTS engine has a voice for '{lang}'.",
            "Install a Piper or XTTS voice pack for this language.",
        )
    preferred = [v for v in voices if v.gender == gender] if gender in {"male", "female"} else []
    pool = preferred or voices
    return pool[index % len(pool)].id


def assign_speaker_voices(speakers: list[dict], lang: str, *, engine: str | None = None) -> list[dict]:
    """Give every speaker a distinct voice where possible; deterministic."""
    tts = build_tts(engine)
    voices = tts.voices(lang)
    if not voices:
        return speakers
    used: set[str] = set()
    for i, speaker in enumerate(speakers):
        if speaker.get("voice"):
            used.add(speaker["voice"])
            continue
        gender = speaker.get("gender", "unknown")
        pool = [v for v in voices if v.gender == gender] if gender in {"male", "female"} else []
        pool = pool or voices
        choice = next((v for v in pool if v.id not in used), pool[i % len(pool)])
        speaker["voice"] = choice.id
        used.add(choice.id)
    return speakers


def preview(text: str, lang: str, voice_id: str, out_path: Path, *, engine: str | None = None) -> Path:
    tts = build_tts(engine or (voice_id.split(":", 1)[0] if ":" in voice_id else None))
    return tts.synthesize(text, lang, voice_id, out_path)
