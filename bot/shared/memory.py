from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List


@dataclass
class SessionState:
    session_id: str
    call_uuid: str
    phone_number: str
    language: str
    system_prompt_id: str
    flow: dict | None = None
    history: List[dict] = field(default_factory=list)
    user_name: str | None = None
    policies: List[dict] = field(default_factory=list)
    selected_policy: str | None = None
    vehicle_details: str | None = None
    profile_loaded: bool = False
    is_new_customer: bool = False
    caller_phone: str | None = None
    pending_flow: str | None = None
    last_service: str | None = None
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionStore:
    def __init__(self, default_language: str, default_system_prompt_id: str, expire_seconds: int = 0):
        self._sessions: Dict[str, SessionState] = {}
        self.default_language = default_language
        self.default_system_prompt_id = default_system_prompt_id
        self.expire_seconds = max(int(expire_seconds or 0), 0)

    def _is_expired(self, session: SessionState) -> bool:
        if self.expire_seconds <= 0:
            return False
        now = datetime.now(timezone.utc)
        return (now - session.last_active) > timedelta(seconds=self.expire_seconds)

    def _new_session(self, call_uuid: str, phone_number: str) -> SessionState:
        return SessionState(
            session_id=call_uuid,
            call_uuid=call_uuid,
            phone_number=phone_number,
            language=self.default_language,
            system_prompt_id=self.default_system_prompt_id,
            flow=None,
        )

    def get(self, call_uuid: str, phone_number: str, return_expired: bool = False):
        expired = None
        if call_uuid in self._sessions:
            session = self._sessions[call_uuid]
            if self._is_expired(session):
                expired = session
                session = self._new_session(call_uuid, phone_number)
                self._sessions[call_uuid] = session
            else:
                session.phone_number = phone_number or session.phone_number
            session.last_active = datetime.now(timezone.utc)
            return (session, expired) if return_expired else session

        session = self._new_session(call_uuid, phone_number)
        self._sessions[call_uuid] = session
        session.last_active = datetime.now(timezone.utc)
        return (session, None) if return_expired else session

    def reset(self, session_id: str) -> SessionState:
        session = self._new_session(session_id, "")
        self._sessions[session_id] = session
        session.last_active = datetime.now(timezone.utc)
        return session
