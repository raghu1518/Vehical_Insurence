from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bot.infrastructure.config import SETTINGS


def _transcript_path(call_uuid: str) -> Path:
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_dir = SETTINGS.logging.dir / "transcripts" / date_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    safe_uuid = call_uuid.replace("/", "_").replace("\\", "_")
    return base_dir / f"{safe_uuid}.jsonl"


def append_transcript(call_uuid: str, user_type: str, message: str) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_type": user_type,
        "message": message,
    }
    path = _transcript_path(call_uuid)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
