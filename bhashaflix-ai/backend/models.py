"""Domain models and the honest stage machine."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

# The nine user-visible stages, in order.  Nothing else is shown to users.
STAGE_ORDER: list[str] = [
    "uploading",
    "extracting_audio",
    "transcribing",
    "identifying_speakers",
    "translating",
    "generating_voices",
    "synchronizing_audio",
    "rendering",
    "completed",
]

STAGE_LABELS: dict[str, dict[str, str]] = {
    "queued": {"en": "Queued", "hi": "कतार में"},
    "uploading": {"en": "Uploading", "hi": "अपलोड हो रहा है"},
    "extracting_audio": {"en": "Extracting audio", "hi": "ऑडियो निकाला जा रहा है"},
    "transcribing": {"en": "Transcribing dialogue", "hi": "संवाद लिखा जा रहा है"},
    "identifying_speakers": {"en": "Identifying speakers", "hi": "वक्ताओं की पहचान"},
    "translating": {"en": "Translating dialogue", "hi": "संवाद अनुवाद"},
    "generating_voices": {"en": "Generating AI voices", "hi": "AI आवाज़ बन रही है"},
    "synchronizing_audio": {"en": "Synchronizing audio", "hi": "ऑडियो सिंक हो रहा है"},
    "rendering": {"en": "Rendering final video", "hi": "अंतिम वीडियो बन रहा है"},
    "completed": {"en": "Completed", "hi": "पूरा हुआ"},
    "failed": {"en": "Failed", "hi": "विफल"},
    "cancelled": {"en": "Cancelled", "hi": "रद्द"},
}

JobStatus = Literal["queued", "running", "awaiting_input", "completed", "failed", "cancelled"]


@dataclass
class Segment:
    """One line of dialogue.  Times are seconds in the original timeline."""

    id: int
    start: float
    end: float
    text: str
    speaker: str = "SPEAKER_01"
    translated_text: str = ""
    confidence: float | None = None
    # Raw duration of the generated TTS before time-fitting (seconds)
    tts_duration: float | None = None
    # Applied tempo factor (1.0 = untouched)
    tempo: float | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 3)
        return d

    @classmethod
    def from_row(cls, row) -> "Segment":
        import json

        flags = row["flags"]
        try:
            flags = json.loads(flags) if flags else []
        except Exception:
            flags = []
        return cls(
            id=row["idx"],
            start=row["start_sec"],
            end=row["end_sec"],
            text=row["text"] or "",
            speaker=row["speaker"] or "SPEAKER_01",
            translated_text=row["translated_text"] or "",
            confidence=row["confidence"],
            tts_duration=row["tts_duration"],
            tempo=row["tempo"],
            flags=flags,
        )


@dataclass
class Speaker:
    id: str
    label: str
    gender: str = "unknown"
    voice: str = ""
    segments: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# Error catalogue: every failure carries a stable code and an actionable hint.
ERROR_CATALOGUE: dict[str, dict[str, str]] = {
    "UNSUPPORTED_FORMAT": {
        "en": "This file type is not supported. Use MP4, MKV or MOV.",
        "hi": "यह फ़ाइल प्रकार समर्थित नहीं है। MP4, MKV या MOV इस्तेमाल करें।",
    },
    "FILE_TOO_LARGE": {
        "en": "The file is larger than the server upload limit.",
        "hi": "फ़ाइल सर्वर की अपलोड सीमा से बड़ी है।",
    },
    "CORRUPT_MEDIA": {
        "en": "The video could not be read. It may be corrupt or truncated.",
        "hi": "वीडियो पढ़ा नहीं जा सका। हो सकता है फ़ाइल ख़राब हो।",
    },
    "NO_AUDIO_STREAM": {
        "en": "No audio track found — there is no dialogue to dub.",
        "hi": "कोई ऑडियो ट्रैक नहीं मिला — डब करने के लिए संवाद नहीं है।",
    },
    "DURATION_TOO_LONG": {
        "en": "The clip is longer than this server allows.",
        "hi": "क्लिप इस सर्वर की सीमा से लंबी है।",
    },
    "DURATION_TOO_SHORT": {
        "en": "The clip is too short to process.",
        "hi": "क्लिप प्रोसेस करने के लिए बहुत छोटी है।",
    },
    "ASR_UNAVAILABLE": {
        "en": "No speech-recognition model is installed on this backend.",
        "hi": "इस बैकएंड पर स्पीच-रिकग्निशन मॉडल इंस्टॉल नहीं है।",
    },
    "TRANSCRIBE_FAILED": {
        "en": "Speech recognition could not produce dialogue for this audio.",
        "hi": "इस ऑडियो से संवाद नहीं निकल सका।",
    },
    "UNSUPPORTED_LANGUAGE": {
        "en": "The requested language is not supported by the installed models.",
        "hi": "मांगी गई भाषा इंस्टॉल किए मॉडल में समर्थित नहीं है।",
    },
    "TRANSLATE_UNAVAILABLE": {
        "en": "No translation model is installed on this backend.",
        "hi": "इस बैकएंड पर अनुवाद मॉडल इंस्टॉल नहीं है।",
    },
    "TRANSLATE_FAILED": {
        "en": "Translation failed for one or more lines.",
        "hi": "एक या अधिक पंक्तियों का अनुवाद विफल रहा।",
    },
    "TTS_UNAVAILABLE": {
        "en": "No text-to-speech engine is available for this language.",
        "hi": "इस भाषा के लिए कोई टेक्स्ट-टू-स्पीच इंजन उपलब्ध नहीं है।",
    },
    "TTS_FAILED": {
        "en": "Voice generation failed.",
        "hi": "आवाज़ बनाने में विफलता।",
    },
    "AUDIO_EXTRACTION_FAILED": {
        "en": "The audio track could not be extracted.",
        "hi": "ऑडियो ट्रैक नहीं निकाला जा सका।",
    },
    "AUDIO_SYNC_FAILED": {
        "en": "The dubbed audio could not be aligned to the original timing.",
        "hi": "डब ऑडियो मूल समय के साथ मेल नहीं खा सका।",
    },
    "RENDER_FAILED": {
        "en": "The final video could not be rendered.",
        "hi": "अंतिम वीडियो रेंडर नहीं हो सका।",
    },
    "OUT_OF_MEMORY": {
        "en": "The server ran out of memory. Try a shorter clip.",
        "hi": "सर्वर की मेमोरी ख़त्म हो गई। छोटी क्लिप आज़माएँ।",
    },
    "GPU_UNAVAILABLE": {
        "en": "This stage needs a GPU that is not available right now.",
        "hi": "इस चरण के लिए GPU चाहिए जो अभी उपलब्ध नहीं है।",
    },
    "PROCESSING_TIMEOUT": {
        "en": "Processing took too long and was stopped.",
        "hi": "प्रोसेसिंग बहुत लंबी हो गई और रोक दी गई।",
    },
    "STORAGE_LIMIT": {
        "en": "Server storage is full. Delete old projects and retry.",
        "hi": "सर्वर स्टोरेज भर गया है। पुराने प्रोजेक्ट हटाकर फिर कोशिश करें।",
    },
    "FFMPEG_MISSING": {
        "en": "FFmpeg is missing on the server.",
        "hi": "सर्वर पर FFmpeg नहीं है।",
    },
    "NO_DIALOGUE": {
        "en": "No dialogue was found, so there is nothing to dub.",
        "hi": "कोई संवाद नहीं मिला, इसलिए डब करने को कुछ नहीं है।",
    },
    "PROBE_UNAVAILABLE": {
        "en": "Media inspection tooling is not available on this server.",
        "hi": "इस सर्वर पर मीडिया जाँच उपलब्ध नहीं है।",
    },
    "INTERNAL_ERROR": {
        "en": "An unexpected server error occurred.",
        "hi": "सर्वर में अप्रत्याशित त्रुटि हुई।",
    },
    "JOB_NOT_FOUND": {"en": "Project not found.", "hi": "प्रोजेक्ट नहीं मिला।"},
    "JOB_BUSY": {"en": "This project is already processing.", "hi": "यह प्रोजेक्ट पहले से प्रोसेस हो रहा है।"},
    "STAGE_OUT_OF_ORDER": {
        "en": "This step needs an earlier step to finish first.",
        "hi": "इस चरण के लिए पहले का चरण पूरा होना ज़रूरी है।",
    },
    "UNAUTHORIZED": {"en": "Missing or invalid access token.", "hi": "एक्सेस टोकन ग़लत या अनुपस्थित है।"},
    "RATE_LIMITED": {"en": "Too many requests. Please slow down.", "hi": "बहुत ज़्यादा अनुरोध। कृपया धीरे करें।"},
    "QUOTA_EXCEEDED": {"en": "Allowed content is limited to material you own or may process.", "hi": "केवल अपनी या अनुमति प्राप्त सामग्री ही प्रोसेस करें।"},
}


def error_payload(code: str, detail: str | None = None, hint: str | None = None) -> dict:
    entry = ERROR_CATALOGUE.get(code, ERROR_CATALOGUE["INTERNAL_ERROR"])
    return {
        "code": code,
        "message": entry["en"],
        "message_hi": entry["hi"],
        "detail": detail,
        "hint": hint,
    }
