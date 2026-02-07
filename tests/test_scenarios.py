import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot.application.flows import (
    ClaimFlow,
    FlowAgent,
    OnboardingFlow,
    extract_policy_choice,
    _invalid_pincode,
)
from bot.infrastructure.config import SETTINGS
from bot.shared.datetime_parser import ParsedDateTime
from bot.shared.i18n import get_message, matches_intent
from bot.shared.memory import SessionStore
from bot.shared.tools import tool_claim_payment


def _make_session(phone="9999999999", call_uuid="test-call"):
    store = SessionStore(default_language="en", default_system_prompt_id="core-multi", expire_seconds=0)
    return store.get(call_uuid, phone)


def test_onboarding_policy_selection_extract():
    policies = [
        {"policy_number": "POL-502", "vehicle_reg_number": "TN-09-EE-7777"},
        {"policy_number": "POL-501", "vehicle_reg_number": "TN-09-DD-6666"},
    ]
    assert extract_policy_choice("pol501", policies) == "POL-501"
    assert extract_policy_choice("pol 501", policies) == "POL-501"
    assert extract_policy_choice("TN-09-DD-6666", policies) == "POL-501"
    assert extract_policy_choice("6666", policies) == "POL-501"


def test_onboarding_policy_selection_flow():
    session = _make_session()
    session.policies = [
        {"policy_number": "POL-502", "vehicle_reg_number": "TN-09-EE-7777"},
        {"policy_number": "POL-501", "vehicle_reg_number": "TN-09-DD-6666"},
    ]
    flow_state = {"name": "onboarding", "step": "select_policy", "data": {}}

    async def run():
        outcome = await OnboardingFlow().handle(flow_state, session, "pol 501", "en")
        return outcome

    outcome = asyncio.run(run())
    assert session.selected_policy == "POL-501"
    assert "POL-501" in outcome.reply


def test_claim_date_validation_today(monkeypatch):
    tz = ZoneInfo(SETTINGS.timezone)
    now = datetime.now(tz)

    def _mock_parse(text, now=None):
        return ParsedDateTime(value=now.replace(hour=0, minute=0, second=0, microsecond=0), had_time=False)

    monkeypatch.setattr("bot.application.flows.parse_natural_datetime", _mock_parse)

    flow = ClaimFlow()
    session = _make_session()
    flow_state = {"name": "claim", "step": "incident_date", "data": {}}

    async def run():
        return await flow.handle(flow_state, session, "today", "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "location"
    assert get_message("claim_prompt_location", "en") in outcome.reply


def test_claim_date_validation_future(monkeypatch):
    tz = ZoneInfo(SETTINGS.timezone)
    now = datetime.now(tz)
    future = now + timedelta(days=1)

    def _mock_parse(text, now=None):
        return ParsedDateTime(value=future, had_time=False)

    monkeypatch.setattr("bot.application.flows.parse_natural_datetime", _mock_parse)

    flow = ClaimFlow()
    session = _make_session()
    flow_state = {"name": "claim", "step": "incident_date", "data": {}}

    async def run():
        return await flow.handle(flow_state, session, "tomorrow", "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "incident_date"
    assert get_message("claim_invalid_future_date", "en") in outcome.reply


def test_claim_date_validation_invalid(monkeypatch):
    def _mock_parse(text, now=None):
        return None

    monkeypatch.setattr("bot.application.flows.parse_natural_datetime", _mock_parse)

    flow = ClaimFlow()
    session = _make_session()
    flow_state = {"name": "claim", "step": "incident_date", "data": {}}

    async def run():
        return await flow.handle(flow_state, session, "not-a-date", "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "incident_date"
    assert get_message("claim_invalid_date", "en") in outcome.reply


def test_pincode_length_validation():
    assert _invalid_pincode("12345") is True
    assert _invalid_pincode("1234567") is True
    assert _invalid_pincode("kphb 50073") is True
    assert _invalid_pincode("kphb 500072") is False
    assert _invalid_pincode("123456") is False


def test_pincode_rejected_in_claim_location():
    flow = ClaimFlow()
    session = _make_session()
    flow_state = {"name": "claim", "step": "location", "data": {}}

    async def run():
        return await flow.handle(flow_state, session, "1234567", "en")

    outcome = asyncio.run(run())
    assert get_message("pincode_invalid", "en") in outcome.reply
    assert outcome.flow_state["step"] == "location"


def test_unregistered_flow_existing_vs_new():
    async def existing_classifier(message, language):
        return "existing"

    async def new_classifier(message, language):
        return "new"

    session_existing = _make_session(call_uuid="unreg-existing")
    session_existing.flow = {"name": "unregistered", "step": "customer_type", "data": {}}

    async def run_existing():
        agent = FlowAgent(customer_type_classifier=existing_classifier)
        return await agent.handle("existing", session_existing, "en")

    outcome_existing = asyncio.run(run_existing())
    assert outcome_existing.flow_state["step"] == "existing_phone"

    session_new = _make_session(call_uuid="unreg-new")
    session_new.flow = {"name": "unregistered", "step": "customer_type", "data": {}}

    async def run_new():
        agent = FlowAgent(customer_type_classifier=new_classifier)
        return await agent.handle("new", session_new, "en")

    outcome_new = asyncio.run(run_new())
    assert outcome_new.flow_state["step"] == "new_help"


def test_claim_payment_intent():
    message = "When will my claim payment be processed?"
    assert matches_intent(message, "claim_payment") is True
    result = tool_claim_payment("en")
    assert "4 to 7" in result.content


def test_no_more_help_sendoff():
    message = "nothing else"
    assert matches_intent(message, "no_more_help") is True
    assert get_message("assist_sendoff", "en")


def test_help_options_intent_match():
    message = "How can you help me?"
    assert matches_intent(message, "help_options") is True


def test_flow_agent_skips_flow_start_for_no_more_help():
    async def always_hospital(message, language):
        return "hospital"

    session = _make_session(call_uuid="no-more-help")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(flow_classifier=always_hospital)
        return await agent.handle("nothing else", session, "en")

    outcome = asyncio.run(run())
    assert outcome is None


def test_flow_agent_skips_flow_start_for_claim_payment():
    async def always_claim(message, language):
        return "claim"

    session = _make_session(call_uuid="claim-payment")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(flow_classifier=always_claim)
        return await agent.handle("When will my claim payment be processed?", session, "en")

    outcome = asyncio.run(run())
    assert outcome is None


def test_resume_pending_accident_after_policy_selection():
    session = _make_session(call_uuid="pending-accident")
    session.flow = {"name": "onboarding", "step": "select_policy", "data": {}}
    session.policies = [
        {"policy_number": "POL-502", "vehicle_reg_number": "TN-09-EE-7777"},
        {"policy_number": "POL-501", "vehicle_reg_number": "TN-09-DD-6666"},
    ]
    session.pending_flow = "accident"

    async def run():
        agent = FlowAgent()
        return await agent.handle("7777", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_start"
    assert outcome.flow_state["name"] == "accident"


def test_hospital_followup_prefers_hospital_context_over_router():
    async def always_roadside(message, language):
        return "roadside"

    session = _make_session(call_uuid="hospital-followup")
    session.profile_loaded = True
    session.last_service = "hospital"

    async def run():
        agent = FlowAgent(flow_classifier=always_roadside)
        return await agent.handle("can you find other one at kphb 50073", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "hospital_step"
    assert get_message("pincode_invalid", "en") in outcome.reply


def test_flow_interruption_for_help_options_keeps_flow():
    session = _make_session(call_uuid="flow-interrupt")
    session.profile_loaded = True
    session.flow = {"name": "claim", "step": "location", "data": {}}

    async def run():
        agent = FlowAgent()
        return await agent.handle("How can you help me?", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "flow_interruption"
    assert get_message("faq_can_do", "en") in outcome.reply
    assert get_message("claim_prompt_location", "en") in outcome.reply
    assert outcome.flow_state["name"] == "claim"
    assert outcome.flow_state["step"] == "location"
