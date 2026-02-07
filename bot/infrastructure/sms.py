from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Union

import requests

from .config import SETTINGS
from .db import get_telegram_chat_id_sync

log = logging.getLogger("sms")


def send_telegram_message(
    chat_id: Union[int, str],
    message: str,
    bot_token: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Send a Telegram message using a bot.

    chat_id: user_id or chat_id (for private chats, user_id works as chat_id)
    message: text to send
    bot_token: bot token (if None, reads TELEGRAM_BOT_TOKEN from env/settings)
    Returns: Telegram API JSON response (raises on HTTP errors)
    """
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or SETTINGS.telegram.bot_token
    if not token:
        raise ValueError("Bot token missing. Provide bot_token or set TELEGRAM_BOT_TOKEN.")

    if chat_id is None or str(chat_id).strip() == "":
        raise ValueError("chat_id missing. Provide chat_id or set TELEGRAM_CHAT_ID.")
    if not message or not str(message).strip():
        raise ValueError("message text is empty.")

    safe_chat_id = str(chat_id).strip()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": safe_chat_id,
        "text": message,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    resp = requests.post(url, json=payload, timeout=timeout)
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body = resp.text
        log.error(
            "telegram_http_error status=%s chat_id=%s body=%s",
            resp.status_code,
            safe_chat_id,
            body,
        )
        raise RuntimeError(f"Telegram HTTP {resp.status_code}: {body}") from exc

    data = resp.json()

    if not data.get("ok", False):
        log.error("telegram_api_error", extra={"response": data, "chat_id": safe_chat_id})
        raise RuntimeError(f"Telegram API error: {data}")

    return data


def send_sms(
    message: str,
    chat_id: Optional[Union[int, str]] = None,
    phone_no: Optional[str] = None,
    bot_token: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
    timeout: int = 10,
) -> Dict[str, Any]:
    if not SETTINGS.telegram.sms_enabled:
        log.info("sms_disabled")
        return {"ok": False, "disabled": True}
    resolved_chat_id = None
    if phone_no:
        resolved_chat_id = get_telegram_chat_id_sync(phone_no)
    if not resolved_chat_id:
        resolved_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or SETTINGS.telegram.chat_id
    return send_telegram_message(
        chat_id=resolved_chat_id,
        message=message,
        bot_token=bot_token,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        timeout=timeout,
    )


async def send_sms_async(
    message: str,
    chat_id: Optional[Union[int, str]] = None,
    phone_no: Optional[str] = None,
    bot_token: Optional[str] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = True,
    timeout: int = 10,
) -> bool:
    if not SETTINGS.telegram.sms_enabled:
        log.info("sms_disabled")
        return False
    try:
        await asyncio.to_thread(
            send_sms,
            message,
            chat_id,
            phone_no,
            bot_token,
            parse_mode,
            disable_web_page_preview,
            timeout,
        )
        return True
    except Exception:
        log.exception("sms_send_failed")
        return False
