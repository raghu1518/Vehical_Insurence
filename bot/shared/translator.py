from __future__ import annotations

import logging
from functools import lru_cache

from bot.infrastructure.config import SETTINGS
from bot.infrastructure.llm_clients import build_client, LLMError

log = logging.getLogger("translator")

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "as": "Assamese",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "or": "Odia",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ne": "Nepali",
    "sa": "Sanskrit",
    "ur": "Urdu",
    "ks": "Kashmiri",
    "sd": "Sindhi",
    "kok": "Konkani",
    "mai": "Maithili",
    "brx": "Bodo",
    "doi": "Dogri",
    "mni": "Manipuri (Meitei)",
    "sat": "Santali",
}


@lru_cache(maxsize=1024)
def translate_text(text: str, target_lang: str) -> str:
    if not text:
        return text
    lang = target_lang.lower()
    if lang in {"en", "hi"}:
        return text

    language_name = _LANGUAGE_NAMES.get(lang, lang)

    try:
        client = build_client(SETTINGS.llm)
        prompt = (
            f"Translate the following text to {language_name}. "
            "Return only the translation without quotes."
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]
        response = client.generate(messages, system_prompt=None)
        translated = response.content.strip()
        return translated or text
    except LLMError:
        log.warning("translation_failed", extra={"language": lang})
        return text
    except Exception:
        log.exception("translation_error", extra={"language": lang})
        return text
