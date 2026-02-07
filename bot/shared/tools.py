from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import re
from typing import Any

from bot.infrastructure.config import ROOT_DIR, SETTINGS
from .i18n import detect_faq_type, get_message
from bot.infrastructure.sms import send_sms
from bot.infrastructure.search import search_garages, search_hospitals

CALENDAR_PATH = ROOT_DIR / "data" / "calendar.json"


@dataclass
class ToolResult:
    name: str
    content: str
    data: dict[str, Any] | None = None


def _load_calendar() -> dict:
    if not CALENDAR_PATH.exists():
        return {"events": []}
    with CALENDAR_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_calendar(payload: dict) -> None:
    with CALENDAR_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def tool_time(language: str) -> ToolResult:
    tz = ZoneInfo(SETTINGS.timezone)
    now = datetime.now(tz)
    content = get_message(
        "time",
        language,
        time=now.strftime("%H:%M"),
        date=now.strftime("%Y-%m-%d"),
    )
    return ToolResult(name="time", content=content, data={"iso": now.isoformat()})


def tool_greeting(language: str) -> ToolResult:
    return ToolResult(name="greeting", content=get_message("greeting", language))


def tool_sendoff(language: str) -> ToolResult:
    return ToolResult(name="sendoff", content=get_message("sendoff", language))


def tool_claim_payment(language: str) -> ToolResult:
    return ToolResult(name="claim_payment", content=get_message("claim_payment_eta", language))


def tool_faq(question: str, language: str) -> ToolResult | None:
    faq_type, matched_language = detect_faq_type(question)
    if not faq_type:
        return None
    reply_lang = matched_language or language
    return ToolResult(name="faq", content=get_message(f"faq_{faq_type}", reply_lang))


def tool_hospital_search(query: str, language: str) -> ToolResult:
    results = search_hospitals(query)
    if not results:
        return ToolResult(name="hospital_search", content=get_message("hospital_no_result", language))
    hospital = results[0]
    address = hospital.get("address") or hospital.get("city") or ""
    content = get_message(
        "hospital_result",
        language,
        name=hospital.get("name") or "Hospital",
        address=address,
        phone=hospital.get("phone") or "",
    )
    return ToolResult(name="hospital_search", content=content, data=hospital)


def tool_garage_search(query: str, language: str) -> ToolResult:
    results = search_garages(query)
    if not results:
        return ToolResult(name="garage_search", content=get_message("garage_no_result", language))
    garage = results[0]
    address = garage.get("address") or garage.get("city") or ""
    phone = str(garage.get("phone") or "").strip()
    digits = re.sub(r"\D+", "", phone)
    if len(digits) >= 6:
        content = get_message(
            "garage_result_with_phone",
            language,
            name=garage.get("name") or "Garage",
            address=address,
            phone=phone,
        )
    else:
        content = get_message(
            "garage_result_no_phone",
            language,
            name=garage.get("name") or "Garage",
            address=address,
        )
    return ToolResult(name="garage_search", content=content, data=garage)


def tool_sms(message: str, language: str, chat_id: str | None = None, phone_no: str | None = None) -> ToolResult:
    try:
        response = send_sms(message=message, chat_id=chat_id, phone_no=phone_no)
        content = get_message("sms_sent", language)
        return ToolResult(name="sms", content=content, data={"response": response})
    except Exception as exc:
        content = get_message("sms_failed", language)
        return ToolResult(name="sms", content=content, data={"error": str(exc)})


CALENDAR_ADD_RE = re.compile(
    r"(?:add|create|schedule)\s+event\s+(?P<title>.+?)\s+on\s+(?P<date>\d{4}-\d{2}-\d{2})(?:\s+at\s+(?P<time>\d{2}:\d{2}))?",
    re.IGNORECASE,
)
CALENDAR_ADD_HI_RE = re.compile(
    r"(?:इवेंट|कार्यक्रम)\s+जोड़ो\s+(?P<title>.+?)\s+(?P<date>\d{4}-\d{2}-\d{2})(?:\s+समय\s+(?P<time>\d{2}:\d{2}))?",
    re.IGNORECASE,
)
CALENDAR_REMOVE_RE = re.compile(
    r"(?:remove|delete)\s+event\s+(?P<title>.+)",
    re.IGNORECASE,
)


def parse_add_event(message: str) -> dict[str, str] | None:
    match = CALENDAR_ADD_RE.search(message)
    if not match:
        match = CALENDAR_ADD_HI_RE.search(message)
    if not match:
        return None
    return {
        "title": match.group("title").strip(),
        "date": match.group("date"),
        "time": (match.group("time") or "").strip(),
    }


def parse_remove_event(message: str) -> str | None:
    match = CALENDAR_REMOVE_RE.search(message)
    if not match:
        return None
    return match.group("title").strip()


def tool_calendar_add(title: str, date: str, time: str | None, language: str) -> ToolResult:
    payload = _load_calendar()
    event = {
        "id": str(datetime.utcnow().timestamp()).replace(".", ""),
        "title": title,
        "date": date,
        "time": time or "",
    }
    payload.setdefault("events", []).append(event)
    _save_calendar(payload)

    content = get_message(
        "calendar_add",
        language,
        title=title,
        date=date,
        time=time or "",
    )
    return ToolResult(name="calendar_add", content=content, data=event)


def tool_calendar_list(language: str) -> ToolResult:
    payload = _load_calendar()
    events = payload.get("events", [])
    if not events:
        content = get_message("calendar_list_empty", language)
        return ToolResult(name="calendar_list", content=content, data={"events": []})

    lines = []
    for event in events:
        when = f"{event.get('date', '')} {event.get('time', '')}".strip()
        lines.append(f"- {event.get('title', '')} ({when})")

    header = get_message("calendar_list_header", language)
    content = "\n".join([header, *lines])
    return ToolResult(name="calendar_list", content=content, data={"events": events})


def tool_calendar_remove(title: str, language: str) -> ToolResult:
    payload = _load_calendar()
    events = payload.get("events", [])
    remaining = [e for e in events if title.lower() not in e.get("title", "").lower()]
    removed = len(events) - len(remaining)
    payload["events"] = remaining
    _save_calendar(payload)

    if removed == 0:
        content = get_message("calendar_remove_none", language)
    else:
        content = get_message("calendar_remove_some", language, count=removed)

    return ToolResult(name="calendar_remove", content=content, data={"removed": removed})
