from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bot.infrastructure.config import CONFIG_DIR

SYSTEM_PROMPTS_PATH = CONFIG_DIR / "system_prompts.json"


def load_system_prompts() -> list[dict[str, Any]]:
    if not SYSTEM_PROMPTS_PATH.exists():
        return []
    with SYSTEM_PROMPTS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_system_prompts(prompts: list[dict[str, Any]]) -> None:
    with SYSTEM_PROMPTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)


def get_system_prompt(prompts: list[dict[str, Any]], prompt_id: str | None) -> dict[str, Any] | None:
    if not prompt_id:
        return None
    for prompt in prompts:
        if prompt.get("id") == prompt_id:
            return prompt
    return None


def select_prompt_for_language(
    prompts: list[dict[str, Any]], prompt_id: str | None, language: str
) -> dict[str, Any] | None:
    if prompt_id:
        selected = get_system_prompt(prompts, prompt_id)
        if selected:
            selected_lang = str(selected.get("language", "")).strip().lower()
            if selected_lang in {"", "multi", "any", "und", "*"} or selected_lang == language:
                return selected
    for prompt in prompts:
        if prompt.get("language") == language:
            return prompt
    for prompt in prompts:
        lang = str(prompt.get("language", "")).strip().lower()
        if lang in {"multi", "any", "und", "*"}:
            return prompt
    return prompts[0] if prompts else None
