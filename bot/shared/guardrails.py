from __future__ import annotations

import re

from .i18n import get_message

SENSITIVE_PATTERNS = [
    r"\botp\b",
    r"one[- ]?time password",
    r"password",
    r"passcode",
    r"pin\b",
    r"cvv",
    r"bank account",
    r"card number",
    r"debit card",
    r"credit card",
]

_PATTERN = re.compile("|".join(SENSITIVE_PATTERNS), re.IGNORECASE)


def apply_guardrails(reply: str, language: str) -> str:
    if not reply:
        return reply
    if _PATTERN.search(reply):
        return get_message("guardrail_sensitive", language)
    return reply
