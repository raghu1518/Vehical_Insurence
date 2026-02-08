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

PROMPT_REQUEST_PATTERNS = [
    r"\b(system|developer|hidden|internal)\s+(prompt|instruction|rule|rules)\b",
    r"\b(show|share|reveal|print|dump|tell)\b.{0,40}\b(prompt|instruction|rule|rules)\b",
    r"\bignore\b.{0,40}\b(previous|prior)\b.{0,40}\b(instruction|rule|rules)\b",
    r"\bjailbreak\b",
    r"\bchain[- ]?of[- ]?thought\b",
    r"\bhow are you instructed\b",
]

PROMPT_OUTPUT_PATTERNS = [
    r"\bsystem prompt\b",
    r"\bdeveloper prompt\b",
    r"\bhidden instructions?\b",
    r"\binternal instructions?\b",
]

_SENSITIVE_PATTERN = re.compile("|".join(SENSITIVE_PATTERNS), re.IGNORECASE)
_PROMPT_REQUEST_PATTERN = re.compile("|".join(PROMPT_REQUEST_PATTERNS), re.IGNORECASE | re.DOTALL)
_PROMPT_OUTPUT_PATTERN = re.compile("|".join(PROMPT_OUTPUT_PATTERNS), re.IGNORECASE)


def is_prompt_disclosure_request(message: str) -> bool:
    if not message:
        return False
    return _PROMPT_REQUEST_PATTERN.search(message) is not None


def apply_guardrails(reply: str, language: str) -> str:
    if not reply:
        return reply
    if _SENSITIVE_PATTERN.search(reply):
        return get_message("guardrail_sensitive", language)
    if _PROMPT_OUTPUT_PATTERN.search(reply):
        return get_message("guardrail_prompt", language)
    return reply
