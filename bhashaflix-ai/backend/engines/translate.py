"""Machine translation engines + the honest manual path.

Priority: NLLB-200 (transformers, GPU-friendly) -> Argos Translate (offline
pair packages) -> LibreTranslate service -> OpenAI-compatible LLM API
(server-side key only) -> imported translated subtitles (user supplied).

There is no fake translation: if nothing is installed and the user has not
provided a translation, the job fails with TRANSLATE_UNAVAILABLE.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..services.languages import get_language

log = logging.getLogger("bhashaflix.translate")


class TranslateError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint


@dataclass
class TranslationResult:
    texts: list[str]
    engine: str
    notes: list[str]


# Registers natural spoken dialogue rather than literal word-for-word prose.
LLM_SYSTEM_PROMPT = (
    "You are a professional movie dubbing translator. Translate each numbered subtitle line "
    "from {src} to {tgt}. Rules: keep spoken register, emotion, tone and character relationships; "
    "use natural everyday {tgt} as a dubbing artist would speak it, never literal word-for-word; "
    "keep proper nouns and untranslatable cultural references as they sound; never add commentary; "
    "never merge or split lines; keep each line short enough to say aloud in about the same time. "
    "Reply with JSON only: {{\"lines\": [{{\"id\": <n>, \"text\": \"<translation>\"}}]}}"
)


class BaseTranslator:
    name = "base"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return False, "not implemented"

    def supports(self, src: str, tgt: str) -> bool:
        return src != tgt

    def translate_batch(self, texts: list[str], src: str, tgt: str) -> TranslationResult:
        raise NotImplementedError


class NLLBTranslator(BaseTranslator):
    name = "nllb-200"

    def __init__(self, model_id: str | None = None):
        import torch  # type: ignore
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore

        self._torch = torch
        self.model_id = model_id or settings.translate_model
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.model.eval()

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import transformers  # noqa: F401
            import torch  # noqa: F401
        except Exception:
            return False, "pip install transformers torch (+ ~2.4 GB weights on first run)"
        return True, "ready"

    def supports(self, src: str, tgt: str) -> bool:
        return bool(get_language(src) and get_language(tgt))

    def translate_batch(self, texts: list[str], src: str, tgt: str) -> TranslationResult:
        self.tokenizer.src_lang = get_language(src)["nllb"]
        target_code = get_language(tgt)["nllb"]
        target_id = self.tokenizer.convert_tokens_to_ids(target_code)
        out: list[str] = []
        batch_size = 8
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            inputs = self.tokenizer(chunk, return_tensors="pt", padding=True, truncation=True, max_length=512).to(self.device)
            with self._torch.no_grad():
                generated = self.model.generate(
                    **inputs,
                    forced_bos_token_id=target_id,
                    max_new_tokens=256,
                    num_beams=4,
                )
            out.extend(self.tokenizer.batch_decode(generated, skip_special_tokens=True))
        return TranslationResult(texts=out, engine=self.name, notes=[])


class ArgosTranslator(BaseTranslator):
    name = "argos"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        try:
            import argostranslate.translate  # noqa: F401
        except Exception:
            return False, "pip install argostranslate (+ language packages from argosopentech)"
        return True, "ready"

    def supports(self, src: str, tgt: str) -> bool:
        from argostranslate import translate  # type: ignore

        return any(
            (lang.code == src and any(t.to_code == tgt for t in lang.translations_from))
            for lang in translate.get_installed_languages()
        )

    def translate_batch(self, texts: list[str], src: str, tgt: str) -> TranslationResult:
        from argostranslate import translate  # type: ignore

        langs = {lang.code: lang for lang in translate.get_installed_languages()}
        if src not in langs or tgt not in langs:
            raise TranslateError("UNSUPPORTED_LANGUAGE", f"Argos has no package for {src}->{tgt}.")
        translation = langs[src].get_translation(langs[tgt])
        return TranslationResult(
            texts=[translation.translate(t) for t in texts],
            engine=self.name,
            notes=[],
        )


class LibreTranslateTranslator(BaseTranslator):
    name = "libretranslate"

    def __init__(self, url: str | None = None, api_key: str | None = None):
        self.url = (url or settings.libretranslate_url).rstrip("/")
        self.api_key = api_key or __import__("os").environ.get("BFLIX_LIBRETRANSLATE_KEY", "")
        if not self.url:
            raise TranslateError("TRANSLATE_UNAVAILABLE", "BFLIX_LIBRETRANSLATE_URL is not configured.")

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return (bool(settings.libretranslate_url),
                "set BFLIX_LIBRETRANSLATE_URL to a LibreTranslate instance" if not settings.libretranslate_url else "ready")

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise TranslateError("TRANSLATE_FAILED", f"LibreTranslate HTTP {exc.code}") from exc
        except Exception as exc:
            raise TranslateError("TRANSLATE_FAILED", f"LibreTranslate unreachable: {exc}") from exc

    def translate_batch(self, texts: list[str], src: str, tgt: str) -> TranslationResult:
        payload = {"q": texts, "source": src, "target": tgt, "format": "text"}
        if self.api_key:
            payload["api_key"] = self.api_key
        data = self._post("/translate", payload)
        translated = data.get("translatedText")
        if isinstance(translated, str):
            translated = [translated]
        if not translated or len(translated) != len(texts):
            raise TranslateError("TRANSLATE_FAILED", "LibreTranslate returned an unexpected payload.")
        return TranslationResult(texts=list(translated), engine=self.name, notes=[])


class LLMTranslator(BaseTranslator):
    """Any OpenAI-compatible endpoint (key stays on the server)."""

    name = "llm-api"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        if not self.base_url or not self.api_key:
            raise TranslateError(
                "TRANSLATE_UNAVAILABLE",
                "LLM translation needs BFLIX_LLM_BASE_URL and BFLIX_LLM_API_KEY on the server.",
            )

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        ok = bool(settings.llm_base_url and settings.llm_api_key)
        return ok, "ready" if ok else "set BFLIX_LLM_BASE_URL + BFLIX_LLM_API_KEY (server-side only)"

    def supports(self, src: str, tgt: str) -> bool:
        return True

    def translate_batch(self, texts: list[str], src: str, tgt: str) -> TranslationResult:
        src_name = get_language(src)["en"] if get_language(src) else src
        tgt_name = get_language(tgt)["en"] if get_language(tgt) else tgt
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
        payload = {
            "model": self.model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": LLM_SYSTEM_PROMPT.format(src=src_name, tgt=tgt_name)},
                {"role": "user", "content": numbered},
            ],
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode())
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            lines = parsed.get("lines") or parsed.get("translations") or []
            by_id = {}
            for item in lines:
                if isinstance(item, dict) and "id" in item:
                    by_id[int(item["id"])] = str(item.get("text", ""))
            ordered = [by_id.get(i + 1) for i in range(len(texts))]
            if any(x is None for x in ordered):
                raise TranslateError("TRANSLATE_FAILED", "The LLM response was missing dialogue lines.")
            return TranslationResult(texts=[x or "" for x in ordered], engine=self.name, notes=[])
        except TranslateError:
            raise
        except Exception as exc:
            raise TranslateError("TRANSLATE_FAILED", f"LLM translation failed: {exc}") from exc


class IdentityTranslator(BaseTranslator):
    """Same-language dub (rebuild the audio track without changing wording)."""

    name = "identity"

    @classmethod
    def dependencies_ok(cls) -> tuple[bool, str]:
        return True, "always available"

    def supports(self, src: str, tgt: str) -> bool:
        return True

    def translate_batch(self, texts: list[str], src: str, tgt: str) -> TranslationResult:
        return TranslationResult(texts=list(texts), engine=self.name, notes=["Source and target language are identical."])


TRANSLATOR_CLASSES = [NLLBTranslator, ArgosTranslator, LibreTranslateTranslator, LLMTranslator]


def available_translators() -> list[dict]:
    out = []
    for cls in TRANSLATOR_CLASSES:
        ok, reason = cls.dependencies_ok()
        out.append({"engine": cls.name, "available": ok, "reason": reason})
        # probing or loading heavyweight models here would be wasteful
    return out


def build_translator(engine: str | None = None, src: str = "", tgt: str = "") -> BaseTranslator:
    requested = (engine or settings.translate_engine or "auto").lower()
    if src and tgt and src == tgt:
        return IdentityTranslator()
    mapping = {
        "nllb": NLLBTranslator,
        "nllb-200": NLLBTranslator,
        "argos": ArgosTranslator,
        "libretranslate": LibreTranslateTranslator,
        "llm": LLMTranslator,
        "llm-api": LLMTranslator,
    }
    candidates = [mapping[requested]] if requested in mapping else list(TRANSLATOR_CLASSES)
    errors: list[str] = []
    for cls in candidates:
        ok, reason = cls.dependencies_ok()
        if not ok:
            errors.append(f"{cls.name}: {reason}")
            continue
        try:
            instance = cls()
        except TranslateError as exc:
            errors.append(f"{cls.name}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{cls.name}: {type(exc).__name__}: {exc}")
            continue
        if src and tgt and not instance.supports(src, tgt):
            errors.append(f"{cls.name}: no {src}->{tgt} support installed")
            continue
        return instance
    raise TranslateError(
        "TRANSLATE_UNAVAILABLE",
        "No translation engine is available for this language pair.",
        "Install one (`pip install transformers torch` for NLLB, or `pip install argostranslate`), "
        "configure BFLIX_LLM_BASE_URL/BFLIX_LLM_API_KEY, or import your own translated subtitles. "
        "Checked: " + " | ".join(errors[:3]),
    )


def parse_translated_subtitles(srt_path: Path) -> list[dict]:
    from ..services.srt import read_subtitles

    return read_subtitles(srt_path)
