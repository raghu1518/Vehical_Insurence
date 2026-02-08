from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import re
import secrets
import string
import time
from typing import Any

from bot.infrastructure.db import create_claim, fetch_user_policies
from bot.infrastructure.config import SETTINGS
from bot.shared.datetime_parser import ParsedDateTime, parse_natural_datetime
from bot.shared.i18n import get_message
from bot.infrastructure.search import search_garages, search_hospitals
from bot.infrastructure.sms import send_sms_async

log = logging.getLogger("api")
log.setLevel(getattr(logging, SETTINGS.logging.level.upper(), logging.INFO))

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PIN_RE = re.compile(r"\b\d{6}\b")
PHONE_DIGITS_RE = re.compile(r"\d")
OTP_RE = re.compile(r"\b(\d{4,8})\b")

OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 3
LOCATION_ACK_VALUES = {
    "yes",
    "no",
    "y",
    "n",
    "yeah",
    "yha",
    "ok",
    "okay",
    "sure",
    "ofcourse",
    "of course",
    "haan",
    "ha",
    "nah",
    "nope",
}

HOSPITAL_FOLLOWUP_VALUES = {
    "other hospital",
    "another hospital",
    "other one",
    "another one",
    "one more hospital",
    "find other one",
    "find me other one",
    "find other hospital",
    "get me other hospital",
    "otherone",
}


def _invalid_pincode(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    # Pure numeric input should be exactly 6 digits.
    if raw.isdigit():
        return len(raw) != 6
    # If user included a likely pincode token (5+ digits), enforce 6 digits.
    for token in re.findall(r"\b\d+\b", raw):
        if len(token) >= 5 and len(token) != 6:
            return True
    return False


def _looks_like_location_text(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if raw.lower() in LOCATION_ACK_VALUES:
        return False
    compact = re.sub(r"\s+", "", raw)
    if len(compact) < 3:
        return False
    if not re.search(r"[A-Za-z0-9]", raw):
        return False
    return True


def _looks_like_hospital_followup_request(text: str) -> bool:
    raw = (text or "").strip().lower()
    if not raw:
        return False
    compact = re.sub(r"\s+", " ", raw)
    if compact in HOSPITAL_FOLLOWUP_VALUES:
        return True
    if ("hospital" in compact or "hospial" in compact or "hospitl" in compact) and (
        "other" in compact or "another" in compact or "next" in compact
    ):
        return True
    if "other one" in compact or "another one" in compact or "otherone" in compact:
        return True
    return False


@dataclass
class FlowOutcome:
    reply: str
    flow_state: dict[str, Any] | None
    intent: str


def _bool_from_message(text: str) -> bool | None:
    value = (text or "").strip().lower()
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def _safe_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D+", "", str(value))
    if len(digits) < 6:
        return ""
    return str(value).strip()


def _extract_phone(text: str) -> str | None:
    digits = re.sub(r"\D+", "", text or "")
    if len(digits) < 10:
        return None
    # For Indian numbers, keep last 10 digits.
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def _generate_otp() -> str:
    if not SETTINGS.telegram.sms_enabled:
        return "123456"
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _extract_otp(text: str) -> str | None:
    match = OTP_RE.search(text or "")
    if not match:
        return None
    value = match.group(1)
    if len(value) < 4:
        return None
    return value


def _otp_expired(sent_at: float | None) -> bool:
    if not sent_at:
        return True
    return (time.time() - float(sent_at)) > OTP_TTL_SECONDS


def _is_rsa_eligible(session: Any) -> bool:
    if not getattr(session, "selected_policy", None):
        return False
    policies = getattr(session, "policies", []) or []
    for policy in policies:
        if str(policy.get("policy_number", "")) != str(session.selected_policy):
            continue
        value = policy.get("rsa_covered")
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"yes", "y", "true", "1", "covered", "available", "active"}:
            return True
        if text in {"no", "n", "false", "0", "not", "inactive"}:
            return False
    return False


def format_policy_list(policies: list[dict[str, Any]]) -> str:
    lines = []
    for idx, policy in enumerate(policies, start=1):
        number = policy.get("policy_number", "")
        model = policy.get("vehicle_model", "")
        reg = policy.get("vehicle_reg_number", "")
        policy_type = policy.get("policy_type", "")
        lines.append(f"{idx}. {number} | {model} | {reg} | {policy_type}")
    return "\n".join(lines)


def _normalize_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _tokenize_alnum(text: str) -> list[str]:
    return [t.upper() for t in re.findall(r"[A-Za-z0-9]+", text or "")]


def extract_policy_choice(message: str, policies: list[dict[str, Any]]) -> str | None:
    text = message.strip()
    if not text:
        return None
    # numeric selection (list index)
    if text.isdigit():
        idx = int(text)
        if 1 <= idx <= len(policies):
            return str(policies[idx - 1].get("policy_number", ""))

    norm_query = _normalize_token(text)
    digits_query = _digits_only(text)
    tokens = _tokenize_alnum(text)
    if norm_query and norm_query not in tokens:
        tokens.append(norm_query)
    if digits_query and digits_query not in tokens:
        tokens.append(digits_query)
    try:
        policy_numbers = [str(p.get("policy_number", "")) for p in policies]
        log.info(
            "policy_select_debug message=%s tokens=%s policies=%s",
            text,
            tokens,
            policy_numbers,
        )
    except Exception:
        pass

    for policy in policies:
        number = str(policy.get("policy_number", ""))
        reg = str(policy.get("vehicle_reg_number", ""))
        pol_norm = _normalize_token(number)
        reg_norm = _normalize_token(reg)
        reg_last4 = reg_norm[-4:] if len(reg_norm) >= 4 else ""
        pol_digits = _digits_only(number)
        reg_digits = _digits_only(reg)
        reg_last3 = reg_norm[-3:] if len(reg_norm) >= 3 else ""

        candidates = {
            pol_norm,
            reg_norm,
            pol_digits,
            reg_digits,
            reg_last4,
            reg_last3,
        }
        for token in tokens:
            if not token:
                continue
            for candidate in candidates:
                if not candidate:
                    continue
                if token == candidate:
                    log.info("policy_select_match token=%s candidate=%s policy=%s", token, candidate, number)
                    return number
                if len(token) >= 4 and len(candidate) >= 4:
                    if token in candidate or candidate in token:
                        log.info("policy_select_match token=%s candidate=%s policy=%s", token, candidate, number)
                        return number
    log.info("policy_select_no_match message=%s tokens=%s", text, tokens)
    return None


class OnboardingFlow:
    async def _load_profile(self, session: Any, phone_number: str) -> None:
        profile = await fetch_user_policies(phone_number)
        session.user_name = profile.get("name")
        session.policies = profile.get("policies", [])
        session.profile_loaded = True

    def _greet_from_profile(self, session: Any, language: str) -> FlowOutcome:
        if not session.policies:
            flow = {"name": "onboarding", "step": "manual_policy", "data": {}}
            reply = get_message("onboard_greet_none", language)
            reply = f"{reply}\n{get_message('onboard_select_prompt', language)}"
            return FlowOutcome(reply=reply, flow_state=flow, intent="onboarding")

        if len(session.policies) == 1:
            policy_number = str(session.policies[0].get("policy_number", ""))
            session.selected_policy = policy_number
            name = session.user_name or ""
            reply = get_message(
                "onboard_greet_single",
                language,
                name=name,
                policy_number=policy_number,
            )
            return FlowOutcome(reply=reply, flow_state=None, intent="onboarding")

        policy_list = format_policy_list(session.policies)
        name = session.user_name or ""
        reply = get_message(
            "onboard_greet_multiple",
            language,
            name=name,
            policy_list=policy_list,
        )
        reply = f"{reply}\n{get_message('onboard_select_prompt', language)}"
        flow = {"name": "onboarding", "step": "select_policy", "data": {}}
        return FlowOutcome(reply=reply, flow_state=flow, intent="onboarding")

    async def start(self, session: Any, language: str) -> FlowOutcome:
        await self._load_profile(session, session.phone_number)

        if not session.policies:
            flow = {"name": "unregistered", "step": "customer_type", "data": {}}
            reply = (
                f"{get_message('greeting', language)}\n"
                f"{get_message('unregistered_customer_type', language)}"
            )
            return FlowOutcome(reply=reply, flow_state=flow, intent="unregistered_start")

        return self._greet_from_profile(session, language)

    async def handle(self, flow_state: dict[str, Any], session: Any, message: str, language: str) -> FlowOutcome:
        step = flow_state.get("step")
        if step in {"select_policy", "manual_policy"}:
            log.info("onboarding_policy_input step=%s message=%s", step, message)
            if step == "manual_policy":
                choice = message.strip()
            else:
                choice = extract_policy_choice(message, session.policies)
            if not choice:
                log.info("onboarding_policy_not_found step=%s message=%s", step, message)
                reply = get_message("onboard_invalid", language)
                reply = f"{reply}\n{get_message('onboard_select_prompt', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="onboarding")
            session.selected_policy = choice
            log.info("onboarding_policy_selected policy=%s", choice)
            reply = get_message("onboard_selected", language, policy_number=choice)
            return FlowOutcome(reply=reply, flow_state=None, intent="onboarding")

        return FlowOutcome(reply=get_message("help_prompt", language), flow_state=None, intent="onboarding")


class AccidentFlow:
    def __init__(self, claim_flow: "ClaimFlow") -> None:
        self._claim_flow = claim_flow

    async def start(self, language: str) -> FlowOutcome:
        reply = f"{get_message('accident_empathy', language)} {get_message('accident_safe_prompt', language)}"
        flow = {"name": "accident", "step": "safe", "data": {}}
        return FlowOutcome(reply=reply, flow_state=flow, intent="accident_start")

    async def handle(self, flow_state: dict[str, Any], session: Any, message: str, language: str) -> FlowOutcome:
        step = flow_state.get("step")
        if step == "safe":
            decision = _bool_from_message(message)
            if decision is None:
                reply = get_message("accident_safe_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            flow_state["data"]["safe"] = decision
            flow_state["step"] = "medical"
            reply = get_message("accident_medical_prompt", language)
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

        if step == "medical":
            decision = _bool_from_message(message)
            if decision is None:
                reply = get_message("accident_medical_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            if decision:
                flow_state["step"] = "hospital_location"
                reply = get_message("accident_need_location", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            flow_state["step"] = "drivable"
            reply = get_message("accident_drivable_prompt", language)
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

        if step == "hospital_location":
            query = message.strip()
            if _invalid_pincode(query):
                reply = get_message("pincode_invalid", language)
                reply = f"{reply}\n{get_message('accident_need_location', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            session.last_location_query = query
            results = search_hospitals(query)
            if not results:
                reply = get_message("hospital_no_result", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            hospital = results[0]
            last_name = str(getattr(session, "last_hospital_name", "") or "").strip().lower()
            if last_name and len(results) > 1:
                for candidate in results:
                    cand_name = str(candidate.get("name") or "").strip().lower()
                    if cand_name and cand_name != last_name:
                        hospital = candidate
                        break
            address = hospital.get("address") or hospital.get("city") or ""
            phone = _safe_phone(hospital.get("phone"))
            reply = get_message(
                "hospital_result",
                language,
                name=hospital.get("name") or "Hospital",
                address=address,
                phone=phone,
            )
            sms_key = "hospital_sms_body_with_phone" if phone else "hospital_sms_body_no_phone"
            sms_text = get_message(
                sms_key,
                language,
                name=hospital.get("name") or "Hospital",
                address=address,
                phone=phone,
            )
            sms_sent = await send_sms_async(sms_text, phone_no=session.phone_number)
            if sms_sent:
                reply = f"{reply}\n{get_message('hospital_sms_sent', language)}"
            session.last_hospital_name = hospital.get("name") or ""
            session.last_service = "hospital"
            flow_state["step"] = "drivable"
            reply = f"{reply}\n{get_message('accident_drivable_prompt', language)}"
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

        if step == "drivable":
            decision = _bool_from_message(message)
            if decision is None:
                reply = get_message("accident_drivable_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            if decision:
                flow_state["step"] = "claim_consent"
                reply = get_message("accident_claim_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

            eligible = _is_rsa_eligible(session)
            flow_state["data"]["rsa_eligible"] = eligible
            flow_state["step"] = "rsa_consent"
            offer_key = "accident_rsa_offer_eligible" if eligible else "accident_rsa_offer_paid"
            reply = get_message(offer_key, language)
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

        if step == "rsa_consent":
            decision = _bool_from_message(message)
            if decision is None:
                eligible = bool(flow_state.get("data", {}).get("rsa_eligible"))
                offer_key = "accident_rsa_offer_eligible" if eligible else "accident_rsa_offer_paid"
                reply = get_message(offer_key, language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            if decision:
                flow_state["step"] = "rsa_location"
                reply = get_message("roadside_location_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            flow_state["step"] = "claim_consent"
            reply = get_message("accident_claim_prompt", language)
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

        if step == "rsa_location":
            query = message.strip()
            if _invalid_pincode(query):
                reply = get_message("pincode_invalid", language)
                reply = f"{reply}\n{get_message('roadside_location_prompt', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            results = search_garages(query)
            if not results:
                reply = get_message("garage_no_result", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            garage = results[0]
            phone = _safe_phone(garage.get("phone"))
            if phone:
                reply = get_message(
                    "roadside_result_with_phone",
                    language,
                    name=garage.get("name") or "Garage",
                    phone=phone,
                )
                sms_text = get_message(
                    "roadside_sms_body_with_phone",
                    language,
                    name=garage.get("name") or "Garage",
                    phone=phone,
                )
            else:
                reply = get_message(
                    "roadside_result_base",
                    language,
                    name=garage.get("name") or "Garage",
                )
                sms_text = get_message(
                    "roadside_sms_body_no_phone",
                    language,
                    name=garage.get("name") or "Garage",
                )
            sms_sent = await send_sms_async(sms_text, phone_no=session.phone_number)
            if sms_sent:
                reply = f"{reply}\n{get_message('roadside_sms_sent', language)}"
            flow_state["step"] = "claim_consent"
            reply = f"{reply}\n{get_message('accident_claim_prompt', language)}"
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")

        if step == "claim_consent":
            decision = _bool_from_message(message)
            if decision is None:
                reply = get_message("accident_claim_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_step")
            if decision:
                return await self._claim_flow.start(session, language)
            return FlowOutcome(reply=get_message("accident_followup", language), flow_state=None, intent="accident_complete")

        return FlowOutcome(reply=get_message("accident_followup", language), flow_state=None, intent="accident_complete")


class HospitalFlow:

    async def start(self, language: str) -> FlowOutcome:
        reply = get_message("hospital_prompt_location", language)
        flow = {"name": "hospital", "step": "location", "data": {}}
        return FlowOutcome(reply=reply, flow_state=flow, intent="hospital_start")

    async def handle(self, flow_state: dict[str, Any], session: Any, message: str, language: str) -> FlowOutcome:
        step = flow_state.get("step")
        if step == "location":
            query = message.strip()
            if not query:
                reply = get_message("hospital_prompt_location", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="hospital_step")
            if _invalid_pincode(query):
                reply = get_message("pincode_invalid", language)
                reply = f"{reply}\n{get_message('hospital_prompt_location', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="hospital_step")
            session.last_location_query = query
            results = search_hospitals(query)
            if not results:
                reply = get_message("hospital_no_result", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="hospital_step")
            hospital = results[0]
            last_name = str(getattr(session, "last_hospital_name", "") or "").strip().lower()
            if last_name and len(results) > 1:
                for candidate in results:
                    cand_name = str(candidate.get("name") or "").strip().lower()
                    if cand_name and cand_name != last_name:
                        hospital = candidate
                        break
            address = hospital.get("address") or hospital.get("city") or ""
            phone = _safe_phone(hospital.get("phone"))
            reply = get_message(
                "hospital_result",
                language,
                name=hospital.get("name") or "Hospital",
                address=address,
                phone=phone,
            )
            sms_key = "hospital_sms_body_with_phone" if phone else "hospital_sms_body_no_phone"
            sms_text = get_message(
                sms_key,
                language,
                name=hospital.get("name") or "Hospital",
                address=address,
                phone=phone,
            )
            sms_sent = await send_sms_async(sms_text, phone_no=session.phone_number)
            if sms_sent:
                reply = f"{reply}\n{get_message('hospital_sms_sent', language)}"
            session.last_hospital_name = hospital.get("name") or ""
            session.last_service = "hospital"
            reply = f"{reply}\n{get_message('hospital_followup', language)}"
            return FlowOutcome(reply=reply, flow_state=None, intent="hospital_complete")

        return FlowOutcome(reply=get_message("hospital_followup", language), flow_state=None, intent="hospital_complete")


class RoadsideFlow:

    def _has_vehicle_details(self, session: Any) -> bool:
        if getattr(session, "vehicle_details", None):
            return True
        if session.selected_policy and session.policies:
            for policy in session.policies:
                if str(policy.get("policy_number", "")) == str(session.selected_policy):
                    model = str(policy.get("vehicle_model", "") or "").strip()
                    reg = str(policy.get("vehicle_reg_number", "") or "").strip()
                    return bool(model or reg)
        return False

    async def start(self, session: Any, language: str) -> FlowOutcome:
        has_vehicle = self._has_vehicle_details(session)
        prompt_key = "roadside_prompt_have_vehicle" if has_vehicle else "roadside_prompt_need_vehicle"
        reply = get_message(prompt_key, language)
        step = "location" if has_vehicle else "vehicle"
        flow = {"name": "roadside", "step": step, "data": {}}
        return FlowOutcome(reply=reply, flow_state=flow, intent="roadside_start")

    async def handle(self, flow_state: dict[str, Any], session: Any, message: str, language: str) -> FlowOutcome:
        step = flow_state.get("step")
        if step == "vehicle":
            if not message.strip():
                reply = get_message("roadside_vehicle_missing", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="roadside_step")
            details = message.strip()
            flow_state["data"]["vehicle_details"] = details
            session.vehicle_details = details
            flow_state["step"] = "location"
            reply = get_message("roadside_location_prompt", language)
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="roadside_step")

        if step == "location":
            query = message.strip()
            if _invalid_pincode(query):
                reply = get_message("pincode_invalid", language)
                reply = f"{reply}\n{get_message('roadside_location_prompt', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="roadside_step")
            session.last_location_query = query
            results = search_garages(query)
            if not results:
                reply = get_message("garage_no_result", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="roadside_step")
            garage = results[0]
            phone = _safe_phone(garage.get("phone"))
            if phone:
                reply = get_message(
                    "roadside_result_with_phone",
                    language,
                    name=garage.get("name") or "Garage",
                    phone=phone,
                )
                sms_text = get_message(
                    "roadside_sms_body_with_phone",
                    language,
                    name=garage.get("name") or "Garage",
                    phone=phone,
                )
            else:
                reply = get_message(
                    "roadside_result_base",
                    language,
                    name=garage.get("name") or "Garage",
                )
                sms_text = get_message(
                    "roadside_sms_body_no_phone",
                    language,
                    name=garage.get("name") or "Garage",
                )
            sms_sent = await send_sms_async(sms_text, phone_no=session.phone_number)
            if sms_sent:
                reply = f"{reply}\n{get_message('roadside_sms_sent', language)}"
            session.last_service = "roadside"
            reply = f"{reply}\n{get_message('roadside_followup', language)}"
            return FlowOutcome(reply=reply, flow_state=None, intent="roadside_complete")

        return FlowOutcome(reply=get_message("roadside_followup", language), flow_state=None, intent="roadside_complete")


class ClaimFlow:
    CANCEL_HINTS = [
        "/cancel",
        "cancel",
        "stop",
        "exit",
        "cancel claim",
        "रद्द",
        "बंद",
        "छोड़ो",
        "रोक",
    ]

    def __init__(self, datetime_parser=None) -> None:
        self._datetime_parser = datetime_parser

    def should_cancel(self, message: str) -> bool:
        text = message.lower().strip()
        if text.startswith("/cancel"):
            return True
        return any(hint in text for hint in self.CANCEL_HINTS)

    async def _parse_incident_datetime(
        self,
        text: str,
        language: str,
        now: datetime,
    ) -> ParsedDateTime | None:
        parsed = parse_natural_datetime(text, now=now)
        if parsed:
            return parsed
        if not self._datetime_parser:
            return None
        try:
            return await self._datetime_parser(text, language, now)
        except Exception:
            return None

    async def start(self, session: Any, language: str) -> FlowOutcome:
        data = {}
        if session.selected_policy:
            data["policy_number"] = session.selected_policy
            step = "incident_date"
            reply = get_message("claim_prompt_date", language)
        else:
            step = "policy"
            reply = get_message("claim_start", language)
        flow = {"name": "claim", "step": step, "data": data}
        return FlowOutcome(reply=reply, flow_state=flow, intent="claim_start")

    async def handle(self, flow_state: dict[str, Any], session: Any, message: str, language: str) -> FlowOutcome:
        if self.should_cancel(message):
            return FlowOutcome(reply=get_message("claim_cancelled", language), flow_state=None, intent="claim_cancel")

        step = flow_state.get("step")
        data = flow_state.get("data", {})
        text = message.strip()

        if step == "policy":
            if not text:
                return FlowOutcome(reply=get_message("claim_missing_value", language), flow_state=flow_state, intent="claim_step")
            data["policy_number"] = text
            flow_state["step"] = "incident_date"
            flow_state["data"] = data
            return FlowOutcome(reply=get_message("claim_prompt_date", language), flow_state=flow_state, intent="claim_step")

        if step == "incident_date":
            tz = ZoneInfo(SETTINGS.timezone)
            now = datetime.now(tz)
            parsed_dt = await self._parse_incident_datetime(text, language, now)
            if not parsed_dt:
                reply = get_message("claim_invalid_date", language)
                reply = f"{reply}\n{get_message('claim_prompt_date', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="claim_step")
            if parsed_dt.value.date() > now.date():
                reply = get_message("claim_invalid_future_date", language)
                reply = f"{reply}\n{get_message('claim_prompt_date', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="claim_step")
            data["incident_date"] = parsed_dt.value.date().isoformat()
            data["incident_datetime"] = parsed_dt.value.isoformat()
            flow_state["step"] = "location"
            flow_state["data"] = data
            return FlowOutcome(reply=get_message("claim_prompt_location", language), flow_state=flow_state, intent="claim_step")

        if step == "location":
            if not text:
                return FlowOutcome(reply=get_message("claim_missing_value", language), flow_state=flow_state, intent="claim_step")
            if _invalid_pincode(text):
                reply = get_message("pincode_invalid", language)
                reply = f"{reply}\n{get_message('claim_prompt_location', language)}"
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="claim_step")
            data["location"] = text
            flow_state["step"] = "damage_type"
            flow_state["data"] = data
            return FlowOutcome(reply=get_message("claim_prompt_damage_type", language), flow_state=flow_state, intent="claim_step")

        if step == "damage_type":
            if not text:
                return FlowOutcome(reply=get_message("claim_missing_value", language), flow_state=flow_state, intent="claim_step")
            data["damage_type"] = text
            flow_state["step"] = "description"
            flow_state["data"] = data
            return FlowOutcome(reply=get_message("claim_prompt_description", language), flow_state=flow_state, intent="claim_step")

        if step == "description":
            if not text:
                return FlowOutcome(reply=get_message("claim_missing_value", language), flow_state=flow_state, intent="claim_step")
            data["description"] = text
            flow_state["step"] = "fir_filed"
            flow_state["data"] = data
            return FlowOutcome(reply=get_message("claim_prompt_fir", language), flow_state=flow_state, intent="claim_step")

        if step == "fir_filed":
            decision = _bool_from_message(text)
            if decision is None:
                return FlowOutcome(reply=get_message("yes_no_prompt", language), flow_state=flow_state, intent="claim_step")
            data["fir_filed"] = decision
            if decision:
                flow_state["step"] = "fir_no"
                flow_state["data"] = data
                return FlowOutcome(reply=get_message("claim_prompt_fir_no", language), flow_state=flow_state, intent="claim_step")
            return await self._submit_claim(session, data, language)

        if step == "fir_no":
            if not text:
                return FlowOutcome(reply=get_message("claim_missing_value", language), flow_state=flow_state, intent="claim_step")
            data["fir_no"] = text
            return await self._submit_claim(session, data, language)

        return FlowOutcome(reply=get_message("claim_cancelled", language), flow_state=None, intent="claim_cancel")

    async def _submit_claim(self, session: Any, data: dict[str, Any], language: str) -> FlowOutcome:
        payload = {
            "policy_number": data.get("policy_number"),
            "phone_number": session.phone_number,
            "incident_date": data.get("incident_date"),
            "location": data.get("location"),
            "damage_type": data.get("damage_type"),
            "damage_description": data.get("description"),
            "fir_filed": data.get("fir_filed", False),
            "fir_no": data.get("fir_no"),
        }
        try:
            claim_id = await create_claim(payload)
            reply = get_message("claim_submitted", language, claim_id=claim_id)
            return FlowOutcome(reply=reply, flow_state=None, intent="claim_complete")
        except Exception:
            log.exception("claim_submit_failed")
            reply = get_message("claim_submit_failed", language)
            return FlowOutcome(reply=reply, flow_state=None, intent="claim_error")


class FlowAgent:
    def __init__(
        self,
        yes_no_classifier=None,
        flow_classifier=None,
        customer_type_classifier=None,
        buy_policy_classifier=None,
        intent_classifier=None,
        location_extractor=None,
        response_matcher=None,
        datetime_parser=None,
    ) -> None:
        self.claim_flow = ClaimFlow(datetime_parser=datetime_parser)
        self.accident_flow = AccidentFlow(self.claim_flow)
        self.hospital_flow = HospitalFlow()
        self.roadside_flow = RoadsideFlow()
        self.onboarding_flow = OnboardingFlow()
        self._yes_no_classifier = yes_no_classifier
        self._flow_classifier = flow_classifier
        self._customer_type_classifier = customer_type_classifier
        self._buy_policy_classifier = buy_policy_classifier
        self._intent_classifier = intent_classifier
        self._location_extractor = location_extractor
        self._response_matcher = response_matcher

    async def _start_flow_choice(self, flow_choice: str, session: Any, language: str) -> FlowOutcome | None:
        if flow_choice == "accident":
            return await self.accident_flow.start(language)
        if flow_choice == "hospital":
            return await self.hospital_flow.start(language)
        if flow_choice == "roadside":
            return await self.roadside_flow.start(session, language)
        if flow_choice == "claim":
            return await self.claim_flow.start(session, language)
        return None

    async def _start_accident_with_medical(self, session: Any, language: str, location: str | None) -> FlowOutcome:
        flow_state = {"name": "accident", "step": "hospital_location", "data": {"safe": None}}
        if location:
            return await self.accident_flow.handle(flow_state, session, location, language)
        reply = f"{get_message('accident_empathy', language)} {get_message('accident_need_location', language)}"
        return FlowOutcome(reply=reply, flow_state=flow_state, intent="accident_start")

    def _flow_step_prompt(self, flow_state: dict[str, Any], language: str) -> str | None:
        name = flow_state.get("name")
        step = flow_state.get("step")
        data = flow_state.get("data", {}) or {}

        if name == "accident":
            if step == "safe":
                return get_message("accident_safe_prompt", language)
            if step == "medical":
                return get_message("accident_medical_prompt", language)
            if step == "hospital_location":
                return get_message("accident_need_location", language)
            if step == "drivable":
                return get_message("accident_drivable_prompt", language)
            if step == "rsa_consent":
                eligible = bool(data.get("rsa_eligible"))
                offer_key = "accident_rsa_offer_eligible" if eligible else "accident_rsa_offer_paid"
                return get_message(offer_key, language)
            if step == "rsa_location":
                return get_message("roadside_location_prompt", language)
            if step == "claim_consent":
                return get_message("accident_claim_prompt", language)

        if name == "claim":
            mapping = {
                "policy": "claim_start",
                "incident_date": "claim_prompt_date",
                "location": "claim_prompt_location",
                "damage_type": "claim_prompt_damage_type",
                "description": "claim_prompt_description",
                "fir_filed": "claim_prompt_fir",
                "fir_no": "claim_prompt_fir_no",
            }
            key = mapping.get(step)
            if key:
                return get_message(key, language)

        if name == "hospital":
            if step == "location":
                return get_message("hospital_prompt_location", language)

        if name == "roadside":
            if step == "vehicle":
                return get_message("roadside_prompt_need_vehicle", language)
            if step == "location":
                return get_message("roadside_location_prompt", language)

        if name == "onboarding":
            if step in {"select_policy", "manual_policy"}:
                return get_message("onboard_select_prompt", language)

        return None

    async def _classify_intent(self, message: str, language: str) -> str | None:
        if not self._intent_classifier:
            return None
        try:
            return await self._intent_classifier(message, language)
        except Exception:
            return None

    async def _interrupt_with_tool_or_faq(
        self,
        message: str,
        flow_state: dict[str, Any],
        language: str,
    ) -> FlowOutcome | None:
        intent = await self._classify_intent(message, language)
        if intent in {"no_more_help", "sendoff"}:
            reply = get_message("assist_sendoff", language)
            return FlowOutcome(reply=reply, flow_state=None, intent="assist_sendoff")

        answer = ""
        if intent == "claim_payment":
            answer = get_message("claim_payment_eta", language)
        elif intent == "help_options":
            answer = get_message("faq_can_do", language)

        if not answer:
            return None

        prompt = self._flow_step_prompt(flow_state, language)
        reply = f"{answer}\n{prompt}" if prompt else answer
        return FlowOutcome(reply=reply, flow_state=flow_state, intent="flow_interruption")

    async def _extract_location(self, message: str, language: str) -> str | None:
        if not self._location_extractor:
            return None
        try:
            value = await self._location_extractor(message, language)
        except Exception:
            return None
        value = (value or "").strip()
        if not value:
            return None
        # Accept explicit pincode extraction.
        pin_match = PIN_RE.search(value)
        if pin_match:
            return pin_match.group(0)
        # Reject hallucinated extractor outputs that do not appear in the user text.
        msg_norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (message or "").lower())).strip()
        val_norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.lower())).strip()
        if val_norm and val_norm in msg_norm:
            return value
        return None

    async def _llm_yes_no(self, message: str, context: str, language: str) -> bool | None:
        if not self._yes_no_classifier:
            return None
        try:
            return await self._yes_no_classifier(message, context, language)
        except Exception:
            return None

    async def _llm_is_response(self, message: str, prompt: str | None, language: str) -> bool | None:
        if not self._response_matcher or not prompt:
            return None
        try:
            return await self._response_matcher(message, prompt, language)
        except Exception:
            return None

    async def _detect_flow(self, message: str, language: str) -> str | None:
        if not self._flow_classifier:
            return None
        try:
            return await self._flow_classifier(message, language)
        except Exception:
            return None


    async def _hospital_detour_query(self, message: str, session: Any, language: str) -> str | None:
        text = (message or "").strip()
        location = await self._extract_location(text, language)
        if location:
            return location
        remembered = str(getattr(session, "last_location_query", "") or "").strip()
        if remembered:
            return remembered
        return None

    async def _should_followup_hospital(
        self,
        message: str,
        session: Any,
        language: str,
        intent: str | None = None,
    ) -> bool:
        if str(getattr(session, "last_service", "") or "").lower() != "hospital":
            return False
        explicit_followup = _looks_like_hospital_followup_request(message)
        if intent == "hospital_search":
            return True
        if intent in {"garage_search"}:
            return False
        if session.flow:
            active_flow = str(session.flow.get("name", "") or "").strip().lower()
            active_step = str(session.flow.get("step", "") or "").strip().lower()
            # During RSA location collection, do not hijack into hospital unless explicitly requested.
            if active_flow == "accident" and active_step == "rsa_location":
                return bool(explicit_followup or intent == "hospital_search")
        if explicit_followup:
            return True
        if intent is not None:
            return False
        flow_choice = await self._detect_flow(message, language)
        return flow_choice == "hospital"

    def _resume_current_flow_reply(self, detour_reply: str, flow_state: dict[str, Any], language: str) -> str:
        prompt = self._flow_step_prompt(flow_state, language)
        if not prompt:
            return detour_reply
        if detour_reply.rstrip().endswith(prompt):
            return detour_reply
        return f"{detour_reply}\n{prompt}"

    async def _handle_inflow_detour(
        self,
        message: str,
        session: Any,
        language: str,
        intent: str | None = None,
    ) -> FlowOutcome | None:
        if not session.flow:
            return None

        flow_state = session.flow
        current_flow = str(flow_state.get("name", "")).strip().lower()
        current_step = str(flow_state.get("step", "")).strip().lower()
        if current_flow not in {"accident", "claim", "hospital", "roadside"}:
            return None

        flow_choice = await self._detect_flow(message, language)

        # Keep accident triage deterministic: complete safe/medical first.
        if current_flow == "accident" and current_step in {"safe", "medical"}:
            return None
        # Keep claim data-capture deterministic unless user explicitly requests a hospital/garage search.
        if current_flow == "claim" and current_step in {
            "incident_date",
            "location",
            "damage_type",
            "description",
            "fir_filed",
            "fir_no",
        }:
            if intent not in {"hospital_search", "garage_search"}:
                return None

        hospital_followup = False
        if current_flow == "accident" and current_step in {"safe", "medical", "hospital_location", "drivable", "rsa_consent", "claim_consent", "rsa_location"}:
            if str(getattr(session, "last_service", "") or "").lower() == "hospital":
                is_hospital_request = flow_choice == "hospital" or _looks_like_hospital_followup_request(message)
                if current_step == "rsa_location":
                    is_hospital_request = flow_choice == "hospital"
                if is_hospital_request:
                    if current_step in {"safe", "medical"}:
                        location = await self._extract_location(message, language)
                        hospital_followup = bool(location)
                    elif current_step == "hospital_location":
                        hospital_followup = False
                    else:
                        hospital_followup = True

        if hospital_followup:
            flow_choice = "hospital"

        # Keep accident triage focused unless the user is asking for hospital help.
        if current_flow == "accident" and current_step in {"safe", "medical", "hospital_location"} and flow_choice not in {"hospital"}:
            flow_choice = None

        if current_flow == "accident" and current_step in {"safe", "medical", "drivable", "rsa_consent", "claim_consent"}:
            if flow_choice != "hospital":
                context = "medical" if current_step == "medical" else current_step
                decision = await self._llm_yes_no(message, context, language)
                if decision is not None:
                    return None
        if current_flow == "claim" and current_step == "fir_filed":
            decision = await self._llm_yes_no(message, "fir", language)
            if decision is not None:
                return None

        if flow_choice in {None, "", "none", current_flow}:
            return None

        detour: FlowOutcome | None = None
        if flow_choice == "hospital":
            query = await self._hospital_detour_query(message, session, language)
            if not query:
                hospital_prompt = get_message("hospital_prompt_location", language)
                resumed = self._resume_current_flow_reply(hospital_prompt, flow_state, language)
                return FlowOutcome(reply=resumed, flow_state=flow_state, intent="flow_detour")
            hospital_state = {"name": "hospital", "step": "location", "data": {}}
            detour = await self.hospital_flow.handle(hospital_state, session, query, language)
        elif flow_choice == "roadside":
            detour = await self.roadside_flow.start(session, language)
        elif flow_choice == "claim":
            if session.is_new_customer:
                reply = get_message("claim_not_available_new", language)
                reply = self._resume_current_flow_reply(reply, flow_state, language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="claim_blocked")
            detour = await self.claim_flow.start(session, language)
        elif flow_choice == "accident":
            detour = await self.accident_flow.start(language)

        if not detour:
            return None

        log.info(
            "flow_detour_trigger current_flow=%s current_step=%s requested_flow=%s message=%s",
            current_flow,
            current_step,
            flow_choice,
            message,
        )
        reply = self._resume_current_flow_reply(detour.reply, flow_state, language)
        return FlowOutcome(reply=reply, flow_state=flow_state, intent="flow_detour")

    async def _detect_customer_type(self, message: str, language: str) -> str | None:
        if not self._customer_type_classifier:
            return None
        try:
            return await self._customer_type_classifier(message, language)
        except Exception:
            return None

    async def _detect_buy_policy(self, message: str, language: str) -> bool | None:
        if not self._buy_policy_classifier:
            return None
        try:
            return await self._buy_policy_classifier(message, language)
        except Exception:
            return None

    async def _handle_unregistered(self, flow_state: dict[str, Any], session: Any, message: str, language: str) -> FlowOutcome | None:
        step = flow_state.get("step")
        data = flow_state.get("data", {})

        if step == "customer_type":
            choice = await self._detect_customer_type(message, language)
            if choice not in {"new", "existing"}:
                reply = get_message("unregistered_customer_type", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")
            if choice == "existing":
                flow_state["step"] = "existing_phone"
                reply = get_message("unregistered_existing_phone_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")
            session.is_new_customer = True
            flow_state["step"] = "new_help"
            reply = get_message("unregistered_new_help", language)
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

        if step == "existing_phone":
            phone = _extract_phone(message)
            if not phone:
                reply = get_message("unregistered_existing_phone_invalid", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")
            otp = _generate_otp()
            data["registered_phone"] = phone
            data["otp_code"] = otp
            data["otp_sent_at"] = time.time()
            data["otp_attempts"] = 0
            flow_state["data"] = data

            flow_state["step"] = "otp_verify"
            if not SETTINGS.telegram.sms_enabled:
                reply = (
                    f"{get_message('unregistered_existing_otp_disabled', language, otp=otp)}\n"
                    f"{get_message('unregistered_existing_otp_prompt', language)}"
                )
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

            sms_body = get_message("otp_sms_body", language, otp=otp)
            sent = await send_sms_async(sms_body, phone_no=phone)
            if not sent:
                reply = get_message("unregistered_existing_otp_failed", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

            reply = (
                f"{get_message('unregistered_existing_otp_sent', language, phone=phone)}\n"
                f"{get_message('unregistered_existing_otp_prompt', language)}"
            )
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

        if step == "otp_verify":
            entered = _extract_otp(message)
            if _otp_expired(data.get("otp_sent_at")):
                otp = _generate_otp()
                data["otp_code"] = otp
                data["otp_sent_at"] = time.time()
                data["otp_attempts"] = 0
                flow_state["data"] = data
                if SETTINGS.telegram.sms_enabled:
                    sms_body = get_message("otp_sms_body", language, otp=otp)
                    await send_sms_async(sms_body, phone_no=data.get("registered_phone"))
                    reply = (
                        f"{get_message('unregistered_existing_otp_expired', language)}\n"
                        f"{get_message('unregistered_existing_otp_prompt', language)}"
                    )
                else:
                    reply = (
                        f"{get_message('unregistered_existing_otp_expired', language)}\n"
                        f"{get_message('unregistered_existing_otp_disabled', language, otp=otp)}\n"
                        f"{get_message('unregistered_existing_otp_prompt', language)}"
                    )
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")
            if not entered or entered != str(data.get("otp_code", "")):
                data["otp_attempts"] = int(data.get("otp_attempts", 0)) + 1
                flow_state["data"] = data
                if data["otp_attempts"] >= OTP_MAX_ATTEMPTS:
                    flow_state["step"] = "existing_phone"
                    reply = get_message("unregistered_existing_otp_invalid", language)
                    reply = f"{reply}\n{get_message('unregistered_existing_phone_prompt', language)}"
                    return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")
                reply = get_message("unregistered_existing_otp_invalid", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

            registered_phone = str(data.get("registered_phone", "")).strip()
            if not registered_phone:
                flow_state["step"] = "existing_phone"
                reply = get_message("unregistered_existing_phone_prompt", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

            if not session.caller_phone:
                session.caller_phone = session.phone_number
            session.phone_number = registered_phone
            session.is_new_customer = False
            await self.onboarding_flow._load_profile(session, registered_phone)
            if not session.policies:
                flow_state["step"] = "existing_phone"
                reply = get_message("unregistered_no_policy_found", language)
                return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_step")

            verified_msg = get_message("unregistered_existing_verified", language)
            greet_outcome = self.onboarding_flow._greet_from_profile(session, language)
            if greet_outcome.flow_state:
                flow_state = greet_outcome.flow_state
            else:
                flow_state = None
            reply = f"{verified_msg}\n{greet_outcome.reply}"
            return FlowOutcome(reply=reply, flow_state=flow_state, intent="unregistered_verified")

        if step == "new_help":
            session.is_new_customer = True
            wants_policy = await self._detect_buy_policy(message, language)
            if wants_policy is True:
                reply = get_message("unregistered_new_sales_callback", language)
                return FlowOutcome(reply=reply, flow_state=None, intent="sales_callback")

            flow_choice = await self._detect_flow(message, language)
            if flow_choice == "claim":
                reply = get_message("claim_not_available_new", language)
                return FlowOutcome(reply=reply, flow_state=None, intent="claim_blocked")
            if flow_choice == "accident":
                return await self.accident_flow.start(language)
            if flow_choice == "hospital":
                return await self.hospital_flow.start(language)
            if flow_choice == "roadside":
                return await self.roadside_flow.start(session, language)

            session.flow = None
            return None

        return FlowOutcome(reply=get_message("help_prompt", language), flow_state=None, intent="unregistered_step")

    async def handle(self, message: str, session: Any, language: str) -> FlowOutcome | None:
        active_flow = session.flow.get("name") if session.flow else None
        active_step = session.flow.get("step") if session.flow else None
        log.info(
            "flow_agent_enter flow=%s step=%s profile_loaded=%s is_new_customer=%s message=%s",
            active_flow,
            active_step,
            bool(getattr(session, "profile_loaded", False)),
            bool(getattr(session, "is_new_customer", False)),
            message,
        )
        intent = await self._classify_intent(message, language)
        if intent in {"no_more_help", "sendoff"}:
            if session.flow:
                step = str(session.flow.get("step", "") or "").strip().lower()
                flow_name = str(session.flow.get("name", "") or "").strip().lower()
                critical_yes_no_steps = {"safe", "medical", "drivable", "rsa_consent", "claim_consent", "fir_filed"}
                location_steps = {"hospital_location", "rsa_location"}
                is_location_step = step in location_steps or (
                    step == "location" and flow_name in {"hospital", "roadside", "claim"}
                )
                if step in critical_yes_no_steps:
                    context = "medical" if step == "medical" else step
                    decision = await self._llm_yes_no(message, context, language)
                    if decision is not None:
                        message = "yes" if decision else "no"
                    else:
                        # During critical in-progress flow steps, prioritize step continuation over sendoff.
                        pass
                    if flow_name == "accident":
                        return await self.accident_flow.handle(session.flow, session, message, language)
                    if flow_name == "claim":
                        return await self.claim_flow.handle(session.flow, session, message, language)
                    if flow_name == "hospital":
                        return await self.hospital_flow.handle(session.flow, session, message, language)
                    if flow_name == "roadside":
                        return await self.roadside_flow.handle(session.flow, session, message, language)
                elif is_location_step:
                    # Location collection is also a critical step; do not auto-close on ambiguous "no"/sendoff intents.
                    if flow_name == "accident":
                        return await self.accident_flow.handle(session.flow, session, message, language)
                    if flow_name == "claim":
                        return await self.claim_flow.handle(session.flow, session, message, language)
                    if flow_name == "hospital":
                        return await self.hospital_flow.handle(session.flow, session, message, language)
                    if flow_name == "roadside":
                        return await self.roadside_flow.handle(session.flow, session, message, language)
                else:
                    reply = get_message("assist_sendoff", language)
                    return FlowOutcome(reply=reply, flow_state=None, intent="assist_sendoff")
            else:
                reply = get_message("assist_sendoff", language)
                return FlowOutcome(reply=reply, flow_state=None, intent="assist_sendoff")
        location_hint = await self._extract_location(message, language)
        if session.flow and session.flow.get("name") == "unregistered":
            return await self._handle_unregistered(session.flow, session, message, language)
        if session.flow and session.flow.get("name") == "onboarding":
            onboarding_step = str(session.flow.get("step", "") or "").strip().lower()
            if onboarding_step in {"select_policy", "manual_policy"}:
                hinted = await self._detect_flow(message, language)
                if hinted in {"accident", "hospital", "roadside", "claim"} and not getattr(session, "pending_flow", None):
                    session.pending_flow = hinted
                    log.info("onboarding_pending_flow_set flow=%s message=%s", hinted, message)

            onboarding_outcome = await self.onboarding_flow.handle(session.flow, session, message, language)
            pending_flow = str(getattr(session, "pending_flow", "") or "").strip().lower()
            if onboarding_outcome.flow_state is None and pending_flow:
                session.pending_flow = None
                resumed = await self._start_flow_choice(pending_flow, session, language)
                if resumed:
                    return resumed
            return onboarding_outcome

        if session.flow:
            non_flow_intents = {
                "chat",
                "faq",
                "greeting",
            }
            if intent in non_flow_intents:
                step = str(session.flow.get("step", "") or "").strip().lower()
                flow_name = str(session.flow.get("name", "") or "").strip().lower()
                yes_no_steps = {"safe", "medical", "drivable", "rsa_consent", "claim_consent", "fir_filed"}
                location_steps = {"hospital_location", "rsa_location"}
                is_location_step = step in location_steps or (
                    step == "location" and flow_name in {"hospital", "roadside", "claim"}
                )
                is_structured_step = step in yes_no_steps or is_location_step
                if is_structured_step:
                    yes_no_decision = None
                    step_response_relevant = None
                    if step in yes_no_steps:
                        context = "medical" if step == "medical" else step
                        yes_no_decision = await self._llm_yes_no(message, context, language)
                        prompt = self._flow_step_prompt(session.flow, language)
                        step_response_relevant = await self._llm_is_response(message, prompt, language)
                    has_location = bool(location_hint)
                    if not has_location and is_location_step and PIN_RE.search(message or ""):
                        has_location = True
                    if not has_location and is_location_step and _looks_like_location_text(message):
                        prompt = self._flow_step_prompt(session.flow, language)
                        relevant = await self._llm_is_response(message, prompt, language)
                        if relevant is not False:
                            has_location = True
                    should_scope_block = (
                        is_location_step
                        and yes_no_decision is None
                        and not has_location
                        and step_response_relevant is not True
                    )
                    if should_scope_block:
                        # Allow hospital follow-ups during an active flow.
                        hospital_followup = await self._should_followup_hospital(
                            message, session, language, intent=intent
                        )
                        if not hospital_followup:
                            reply = get_message("guardrail_scope", language)
                            prompt = self._flow_step_prompt(session.flow, language)
                            if prompt:
                                reply = f"{reply}\n{prompt}"
                            return FlowOutcome(reply=reply, flow_state=session.flow, intent="guardrail_scope")
            if session.flow.get("name") == "accident":
                step = str(session.flow.get("step", "") or "").strip().lower()
                if step in {"safe", "medical"} and location_hint and intent == "hospital_search":
                    session.flow["step"] = "hospital_location"
                    return await self.accident_flow.handle(session.flow, session, location_hint, language)
            interruption = await self._interrupt_with_tool_or_faq(message, session.flow, language)
            if interruption:
                return interruption
            detour = await self._handle_inflow_detour(message, session, language, intent=intent)
            if detour:
                return detour

        if session.flow and session.flow.get("name") == "claim":
            if session.flow.get("step") == "fir_filed":
                decision = await self._llm_yes_no(message, "fir", language)
                if decision is not None:
                    message = "yes" if decision else "no"
            return await self.claim_flow.handle(session.flow, session, message, language)
        if session.flow and session.flow.get("name") == "accident":
            step = session.flow.get("step")
            if step in {"safe", "medical", "drivable", "rsa_consent", "claim_consent"}:
                context = "medical" if step == "medical" else step
                decision = await self._llm_yes_no(message, context, language)
                if decision is None:
                    flow_hint = await self._detect_flow(message, language)
                    if step == "safe" and (intent == "hospital_search" or flow_hint in {"hospital", "roadside"}):
                        decision = False
                    elif step == "medical" and (intent == "hospital_search" or flow_hint == "hospital"):
                        decision = True
                    elif step == "drivable" and (intent in {"garage_search"} or flow_hint == "roadside"):
                        decision = False
                if decision is not None:
                    if step == "medical" and decision:
                        location = await self._extract_location(message, language)
                        if location:
                            session.flow["step"] = "hospital_location"
                            return await self.accident_flow.handle(session.flow, session, location, language)
                    message = "yes" if decision else "no"
            return await self.accident_flow.handle(session.flow, session, message, language)
        if session.flow and session.flow.get("name") == "hospital":
            return await self.hospital_flow.handle(session.flow, session, message, language)
        if session.flow and session.flow.get("name") == "roadside":
            return await self.roadside_flow.handle(session.flow, session, message, language)

        if intent in {"claim_payment", "help_options"}:
            return None

        if not session.profile_loaded:
            flow_choice = await self._detect_flow(message, language)
            if flow_choice in {"accident", "hospital", "roadside", "claim"}:
                session.pending_flow = flow_choice
            onboarding_outcome = await self.onboarding_flow.start(session, language)
            pending_flow = str(getattr(session, "pending_flow", "") or "").strip().lower()
            if onboarding_outcome.flow_state is None and pending_flow:
                session.pending_flow = None
                resumed = await self._start_flow_choice(pending_flow, session, language)
                if resumed:
                    return resumed
            return onboarding_outcome

        if await self._should_followup_hospital(message, session, language, intent=intent):
            followup_state = {"name": "hospital", "step": "location", "data": {}}
            followup_query = await self._hospital_detour_query(message, session, language)
            log.info("hospital_followup_resume query=%s message=%s", followup_query, message)
            return await self.hospital_flow.handle(followup_state, session, followup_query, language)

        if session.is_new_customer:
            flow_choice = await self._detect_flow(message, language)
            if flow_choice == "claim":
                reply = get_message("claim_not_available_new", language)
                return FlowOutcome(reply=reply, flow_state=None, intent="claim_blocked")

        flow_choice = await self._detect_flow(message, language)
        if flow_choice == "accident" and location_hint:
            medical_needed = await self._llm_yes_no(message, "medical", language)
            if medical_needed:
                return await self._start_accident_with_medical(session, language, location_hint)
        if flow_choice == "accident" and intent == "hospital_search":
            medical_needed = await self._llm_yes_no(message, "medical", language)
            if medical_needed:
                return await self._start_accident_with_medical(session, language, location_hint)
        started = await self._start_flow_choice(flow_choice or "", session, language)
        if started:
            return started

        return None
