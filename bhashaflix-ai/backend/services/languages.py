"""Language catalogue + script-based language identification.

Text language detection here is deliberately simple and honest: it uses Unicode
script ranges plus a small stop-word test.  It runs without any model download,
and the ASR engine may override it with its own prediction.
"""
from __future__ import annotations

import re

LANGUAGES: list[dict] = [
    {"code": "hi", "en": "Hindi", "native": "हिन्दी", "script": "Devanagari", "nllb": "hin_Deva", "espeak": "hi", "source": True, "target": True},
    {"code": "en", "en": "English", "native": "English", "script": "Latin", "nllb": "eng_Latn", "espeak": "en", "source": True, "target": True},
    {"code": "bho", "en": "Bhojpuri", "native": "भोजपुरी", "script": "Devanagari", "nllb": "bho_Deva", "espeak": "", "source": True, "target": True},
    {"code": "ur", "en": "Urdu", "native": "اردو", "script": "Arabic", "nllb": "urd_Arab", "espeak": "ur", "source": True, "target": True},
    {"code": "ta", "en": "Tamil", "native": "தமிழ்", "script": "Tamil", "nllb": "tam_Taml", "espeak": "ta", "source": True, "target": True},
    {"code": "te", "en": "Telugu", "native": "తెలుగు", "script": "Telugu", "nllb": "tel_Telu", "espeak": "te", "source": True, "target": True},
    {"code": "bn", "en": "Bengali", "native": "বাংলা", "script": "Bengali", "nllb": "ben_Beng", "espeak": "bn", "source": True, "target": True},
    {"code": "mr", "en": "Marathi", "native": "मराठी", "script": "Devanagari", "nllb": "mar_Deva", "espeak": "mr", "source": True, "target": True},
    {"code": "pa", "en": "Punjabi", "native": "ਪੰਜਾਬੀ", "script": "Gurmukhi", "nllb": "pan_Guru", "espeak": "pa", "source": True, "target": True},
    {"code": "gu", "en": "Gujarati", "native": "ગુજરાતી", "script": "Gujarati", "nllb": "guj_Gujr", "espeak": "gu", "source": True, "target": True},
    {"code": "ml", "en": "Malayalam", "native": "മലയാളം", "script": "Malayalam", "nllb": "mal_Mlym", "espeak": "ml", "source": True, "target": True},
    {"code": "kn", "en": "Kannada", "native": "ಕನ್ನಡ", "script": "Kannada", "nllb": "kan_Knda", "espeak": "kn", "source": True, "target": True},
    {"code": "es", "en": "Spanish", "native": "Español", "script": "Latin", "nllb": "spa_Latn", "espeak": "es", "source": True, "target": True},
    {"code": "fr", "en": "French", "native": "Français", "script": "Latin", "nllb": "fra_Latn", "espeak": "fr", "source": True, "target": True},
    {"code": "de", "en": "German", "native": "Deutsch", "script": "Latin", "nllb": "deu_Latn", "espeak": "de", "source": True, "target": True},
    {"code": "ja", "en": "Japanese", "native": "日本語", "script": "Kana/Kanji", "nllb": "jpn_Jpan", "espeak": "ja", "source": True, "target": True},
    {"code": "ko", "en": "Korean", "native": "한국어", "script": "Hangul", "nllb": "kor_Hang", "espeak": "ko", "source": True, "target": True},
    {"code": "zh", "en": "Chinese (Simplified)", "native": "中文", "script": "Han", "nllb": "zho_Hans", "espeak": "cmn", "source": True, "target": True},
    {"code": "ar", "en": "Arabic", "native": "العربية", "script": "Arabic", "nllb": "arb_Arab", "espeak": "ar", "source": True, "target": True},
    {"code": "ru", "en": "Russian", "native": "Русский", "script": "Cyrillic", "nllb": "rus_Cyrl", "espeak": "ru", "source": True, "target": True},
    {"code": "pt", "en": "Portuguese", "native": "Português", "script": "Latin", "nllb": "por_Latn", "espeak": "pt", "source": True, "target": True},
    {"code": "id", "en": "Indonesian", "native": "Bahasa Indonesia", "script": "Latin", "nllb": "ind_Latn", "espeak": "id", "source": True, "target": True},
]

BY_CODE: dict[str, dict] = {lang["code"]: lang for lang in LANGUAGES}

# Bhojpuri is script-identical to Hindi; only NLLB-class models separate them,
# so we surface that limitation instead of silently mislabelling.
SCRIPT_HINTS: list[tuple[str, str]] = [
    (r"[\u0900-\u097F]", "hi"),
    (r"[\u0600-\u06FF\u0750-\u077F]", "ur"),
    (r"[\u0B80-\u0BFF]", "ta"),
    (r"[\u0C00-\u0C7F]", "te"),
    (r"[\u0980-\u09FF]", "bn"),
    (r"[\u0A00-\u0A7F]", "pa"),
    (r"[\u0A80-\u0AFF]", "gu"),
    (r"[\u0D00-\u0D7F]", "ml"),
    (r"[\u0C80-\u0CFF]", "kn"),
    (r"[\u3040-\u30FF]", "ja"),
    (r"[\uAC00-\uD7AF]", "ko"),
    (r"[\u4E00-\u9FFF]", "zh"),
    (r"[\u0400-\u04FF]", "ru"),
    (r"[\u0590-\u05FF]", "he"),
    (r"[\u0E00-\u0E7F]", "th"),
]

WORD_HINTS: dict[str, set[str]] = {
    "en": {"the", "you", "and", "what", "is", "are", "to", "of", "it", "not", "where",
           "going", "this", "that", "have", "will", "with", "for", "my", "your", "we"},
    "es": {"el", "la", "los", "las", "que", "de", "no", "es", "y", "por", "para", "con",
           "una", "un", "esta", "esta", "noche", "vas", "voy", "muy", "pero", "como", "está",
           "quiero", "tengo", "tú", "usted", "dónde", "cuando", "porque", "también", "sí"},
    "fr": {"le", "la", "les", "est", "pas", "que", "pour", "avec", "vous", "dans", "une",
           "des", "je", "tu", "il", "elle", "nous", "mais", "très", "où", "comment", "pourquoi"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "ich", "du", "mit", "ein", "eine",
           "wir", "sie", "aber", "sehr", "wohin", "warum", "auch", "noch", "nach", "zu"},
    "pt": {"o", "a", "que", "não", "de", "para", "com", "uma", "você", "está", "eu", "ele",
           "ela", "nós", "mas", "muito", "onde", "porque", "também", "sim", "estou"},
    "id": {"yang", "dan", "tidak", "aku", "kamu", "untuk", "dengan", "ini", "itu", "saya",
           "kita", "mereka", "tapi", "sangat", "kemana", "kenapa", "juga", "sudah"},
}

# Accents and punctuation that only occur in one of these languages.
CHAR_HINTS: dict[str, str] = {
    "es": "¿¡ñáéíóú",
    "fr": "àâçèéêëîïôùûüœ",
    "de": "äöüß",
    "pt": "ãõçáâêôà",
}

DEVANAGARI_BHOJPURI = {"baa", "haam", "hau", "kaise", "bhail", "raua", "tohar", "hamar", "baani", "kare", "jaa", "rahe", "bhai"}


def get_language(code: str) -> dict | None:
    return BY_CODE.get((code or "").lower())


def is_supported(code: str) -> bool:
    return (code or "").lower() in BY_CODE


def target_languages() -> list[dict]:
    return [lang for lang in LANGUAGES if lang["target"]]


def source_languages() -> list[dict]:
    return [lang for lang in LANGUAGES if lang["source"]]


def detect_text_language(text: str) -> tuple[str, float]:
    """Return (language_code, confidence 0..1) for a block of dialogue text."""
    sample = (text or "").strip()
    if not sample:
        return "unknown", 0.0
    counts: dict[str, int] = {}
    for pattern, code in SCRIPT_HINTS:
        found = len(re.findall(pattern, sample))
        if found:
            counts[code] = counts.get(code, 0) + found
    letters = max(1, len(re.findall(r"\w", sample, flags=re.UNICODE)))
    if counts:
        code, hits = max(counts.items(), key=lambda kv: kv[1])
        if code == "hi" and _looks_bhojpuri(sample):
            return "bho", 0.55
        return code, round(min(0.95, hits / letters + 0.35), 2)
    # Latin script: stop-word vote, boosted by language-specific characters
    lowered = sample.lower()
    words = re.findall(r"[a-zA-Zà-ÿ']+", lowered)
    if not words:
        return "unknown", 0.0
    scores = {code: sum(1 for w in words if w in hints) for code, hints in WORD_HINTS.items()}
    for code, chars in CHAR_HINTS.items():
        hits = sum(lowered.count(c) for c in chars)
        if hits:
            scores[code] = scores.get(code, 0) + hits * 1.5
    best = max(scores.items(), key=lambda kv: kv[1])
    if best[1] < 1:
        return "en", 0.4
    confidence = min(0.9, best[1] / max(1, len(words) * 0.35) + 0.3)
    return best[0], round(confidence, 2)


def _looks_bhojpuri(text: str) -> bool:
    words = set(re.findall(r"[\u0900-\u097F]+", text))
    hits = len(words & DEVANAGARI_BHOJPURI)
    return hits >= 2
