from __future__ import annotations

import asyncio
from typing import Any

from bot.infrastructure.config import Settings
from bot.infrastructure.llm_clients import build_client, LLMError
from bot.shared.guardrails import apply_guardrails
from bot.shared.i18n import LANGUAGE_NAMES


def _format_history(history: list[dict[str, Any]], max_items: int = 24) -> str:
    if not history:
        return ""
    clipped = history[-max_items:]
    lines = []
    for msg in clipped:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        prefix = "User" if role == "user" else "Assistant"
        lines.append(f"{prefix}: {content}")
    return "\n".join(lines)


def _fallback_summary(history: list[dict[str, Any]], max_chars: int) -> str:
    if not history:
        return ""
    recent = [msg for msg in history if msg.get("role") == "user"][-6:]
    text = " | ".join(str(m.get("content", "")).strip() for m in recent if m.get("content"))
    if not text:
        text = "Conversation summary unavailable."
    if max_chars > 0 and len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _summarize_sync(history: list[dict[str, Any]], language: str, settings: Settings, max_chars: int) -> str:
    if not history:
        return ""
    language_name = LANGUAGE_NAMES.get(language, language)
    convo = _format_history(history)
    if not convo:
        return ""

    prompt = (
        "Summarize this chat in 4-6 bullet points. "
        "Include any key details (policy number, incident date/location, requests). "
        "Do NOT include any OTPs, passwords, PINs, or card data. "
        f"Write in {language_name}.\n\n"
        f"{convo}"
    )
    try:
        client = build_client(settings.llm)
        response = client.generate([{"role": "user", "content": prompt}], None)
        summary = response.content.strip()
    except LLMError:
        summary = _fallback_summary(history, max_chars)

    summary = apply_guardrails(summary, language)
    if max_chars > 0 and len(summary) > max_chars:
        summary = summary[: max_chars - 3].rstrip() + "..."
    return summary


async def summarize_history(
    history: list[dict[str, Any]], language: str, settings: Settings, max_chars: int
) -> str:
    return await asyncio.to_thread(_summarize_sync, history, language, settings, max_chars)
