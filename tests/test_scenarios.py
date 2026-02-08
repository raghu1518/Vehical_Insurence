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
from bot.application.orchestrator import FlowStartAgent, IntentAgent, StepResponseAgent, YesNoAgent
from bot.infrastructure.config import SETTINGS
from bot.shared.datetime_parser import ParsedDateTime, parse_natural_datetime
from bot.shared.i18n import get_message
from bot.shared.memory import SessionStore


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


def test_claim_date_llm_fallback_for_telugu(monkeypatch):
    tz = ZoneInfo(SETTINGS.timezone)

    async def llm_date(text, language, now):
        assert language == "te"
        return ParsedDateTime(value=datetime(2026, 2, 8, 15, 0, 0, tzinfo=tz), had_time=True)

    monkeypatch.setattr("bot.application.flows.parse_natural_datetime", lambda text, now=None: None)
    flow = ClaimFlow(datetime_parser=llm_date)
    session = _make_session(call_uuid="claim-date-llm-te")
    flow_state = {"name": "claim", "step": "incident_date", "data": {"policy_number": "POL-501"}}

    async def run():
        return await flow.handle(flow_state, session, "నిన్న మధ్యాహ్నం", "te")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "location"
    assert outcome.flow_state["data"]["incident_date"] == "2026-02-08"
    assert get_message("claim_prompt_location", "te") in outcome.reply


def test_parse_natural_datetime_day_first_month_name_with_time():
    now = datetime(2026, 2, 8, 22, 30, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_datetime("8 feb 2026 10:00 am", now=now)
    assert parsed is not None
    assert parsed.value.year == 2026
    assert parsed.value.month == 2
    assert parsed.value.day == 8
    assert parsed.value.hour == 10
    assert parsed.value.minute == 0


def test_parse_natural_datetime_month_first_date_not_split_from_year():
    now = datetime(2026, 2, 8, 22, 30, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    parsed = parse_natural_datetime("feb 9, 2026 10:00 am", now=now)
    assert parsed is not None
    assert parsed.value.year == 2026
    assert parsed.value.month == 2
    assert parsed.value.day == 9
    assert parsed.value.hour == 10
    assert parsed.value.minute == 0


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


def test_claim_payment_intent_interrupts_flow():
    async def claim_intent(message, language):
        return "claim_payment"

    session = _make_session(call_uuid="claim-payment-intent")
    session.profile_loaded = True
    session.flow = {"name": "claim", "step": "location", "data": {}}

    async def run():
        agent = FlowAgent(intent_classifier=claim_intent)
        return await agent.handle("When will my claim payment be processed?", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "flow_interruption"
    assert "4 to 7" in outcome.reply


def test_no_more_help_sendoff_llm():
    async def no_more_help_intent(message, language):
        return "no_more_help"

    session = _make_session(call_uuid="no-more-help")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(intent_classifier=no_more_help_intent)
        return await agent.handle("nothing else", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "assist_sendoff"
    assert get_message("assist_sendoff", "en") in outcome.reply


def test_flow_agent_skips_flow_start_for_no_more_help():
    async def no_more_help_intent(message, language):
        return "no_more_help"

    async def always_hospital(message, language):
        return "hospital"

    session = _make_session(call_uuid="no-more-help-flow")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(flow_classifier=always_hospital, intent_classifier=no_more_help_intent)
        return await agent.handle("nothing else", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "assist_sendoff"


def test_no_more_help_does_not_end_accident_safe_on_no():
    async def no_more_help_intent(message, language):
        return "no_more_help"

    async def yes_no_safe(message, context, language):
        return False if context == "safe" else None

    session = _make_session(call_uuid="no-more-help-accident-safe")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "safe", "data": {}}

    async def run():
        agent = FlowAgent(intent_classifier=no_more_help_intent, yes_no_classifier=yes_no_safe)
        return await agent.handle("no", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert outcome.flow_state["name"] == "accident"
    assert outcome.flow_state["step"] == "medical"
    assert get_message("accident_medical_prompt", "en") in outcome.reply


def test_no_more_help_does_not_end_accident_safe_when_classifier_uncertain():
    async def no_more_help_intent(message, language):
        return "no_more_help"

    async def yes_no_unknown(*args, **kwargs):
        return None

    session = _make_session(call_uuid="no-more-help-accident-safe-unknown")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "safe", "data": {}}

    async def run():
        agent = FlowAgent(intent_classifier=no_more_help_intent, yes_no_classifier=yes_no_unknown)
        return await agent.handle("not safe", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert outcome.flow_state["name"] == "accident"
    assert outcome.flow_state["step"] == "safe"
    assert get_message("accident_safe_prompt", "en") in outcome.reply


def test_flow_agent_skips_flow_start_for_claim_payment():
    async def always_claim(message, language):
        return "claim"

    async def claim_intent(message, language):
        return "claim_payment"

    session = _make_session(call_uuid="claim-payment")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(flow_classifier=always_claim, intent_classifier=claim_intent)
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

    async def location_extract(message, language):
        return "50073"

    session = _make_session(call_uuid="hospital-followup")
    session.profile_loaded = True
    session.last_service = "hospital"

    async def run():
        agent = FlowAgent(flow_classifier=always_roadside, location_extractor=location_extract)
        return await agent.handle("can you find other one at kphb 50073", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "hospital_step"
    assert get_message("pincode_invalid", "en") in outcome.reply


def test_accident_hospital_detour_resumes_previous_step(monkeypatch):
    async def route_to_hospital(message, language):
        return "hospital"

    async def no_location(message, language):
        return None

    async def no_sms(*args, **kwargs):
        return False

    def fake_search_hospitals(query):
        assert query == "500072"
        return [
            {
                "name": "Amor Hospitals",
                "address": "Balanagar Metro Station, Y Junction, Kukatpally",
                "phone": "04066069999",
            }
        ]

    monkeypatch.setattr("bot.application.flows.send_sms_async", no_sms)
    monkeypatch.setattr("bot.application.flows.search_hospitals", fake_search_hospitals)

    session = _make_session(call_uuid="accident-detour")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}
    session.last_location_query = "500072"

    async def run():
        agent = FlowAgent(flow_classifier=route_to_hospital, location_extractor=no_location)
        return await agent.handle("find me other hospital", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "flow_detour"
    assert outcome.flow_state["name"] == "accident"
    assert outcome.flow_state["step"] == "drivable"
    assert "Nearest hospital" in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply


def test_accident_hospital_detour_beats_llm_yes_no(monkeypatch):
    async def route_none(message, language):
        return "none"

    async def llm_no(*args, **kwargs):
        return False

    async def location_extract(message, language):
        return "kphb"

    async def no_sms(*args, **kwargs):
        return False

    def fake_search_hospitals(query):
        assert query == "kphb"
        return [
            {
                "name": "Preeti Urology & Kidney Hospital",
                "address": "Mig-1, 307, Road No. 4, Kphb Colony",
                "phone": "04023152444",
            }
        ]

    monkeypatch.setattr("bot.application.flows.send_sms_async", no_sms)
    monkeypatch.setattr("bot.application.flows.search_hospitals", fake_search_hospitals)

    session = _make_session(call_uuid="accident-detour-llm")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}
    session.last_service = "hospital"
    session.last_location_query = "kphb"

    async def run():
        agent = FlowAgent(flow_classifier=route_none, yes_no_classifier=llm_no, location_extractor=location_extract)
        return await agent.handle("can you find an other hospital", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "flow_detour"
    assert "Nearest hospital" in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply
    assert "roadside assistance" not in outcome.reply.lower()


def test_flow_interruption_for_help_options_keeps_flow():
    async def help_intent(message, language):
        return "help_options"

    session = _make_session(call_uuid="flow-interrupt")
    session.profile_loaded = True
    session.flow = {"name": "claim", "step": "location", "data": {}}

    async def run():
        agent = FlowAgent(intent_classifier=help_intent)
        return await agent.handle("How can you help me?", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "flow_interruption"
    assert get_message("faq_can_do", "en") in outcome.reply
    assert get_message("claim_prompt_location", "en") in outcome.reply
    assert outcome.flow_state["name"] == "claim"
    assert outcome.flow_state["step"] == "location"


def test_accident_start_skips_safe_when_medical_requested(monkeypatch):
    async def route_accident(message, language):
        return "accident"

    async def yes_medical(message, context, language):
        return True if context == "medical" else None

    async def extract_location(message, language):
        return "kphb"

    async def no_sms(*args, **kwargs):
        return False

    def fake_search_hospitals(query):
        assert query == "kphb"
        return [
            {
                "name": "Preeti Urology & Kidney Hospital",
                "address": "Mig-1, 307, Road No. 4, Kphb Colony",
                "phone": "04023152444",
            }
        ]

    monkeypatch.setattr("bot.application.flows.send_sms_async", no_sms)
    monkeypatch.setattr("bot.application.flows.search_hospitals", fake_search_hospitals)

    session = _make_session(call_uuid="accident-start-medical")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(
            flow_classifier=route_accident,
            yes_no_classifier=yes_medical,
            location_extractor=extract_location,
        )
        return await agent.handle("i had an accident need medical assistance near kphb", session, "en")

    outcome = asyncio.run(run())
    assert "Nearest hospital" in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply


def test_accident_start_plain_accident_does_not_skip_to_medical():
    async def route_accident(message, language):
        return "accident"

    async def intent_chat(message, language):
        return "chat"

    async def yes_medical(*args, **kwargs):
        return True

    session = _make_session(call_uuid="accident-start-plain")
    session.profile_loaded = True

    async def run():
        agent = FlowAgent(
            flow_classifier=route_accident,
            intent_classifier=intent_chat,
            yes_no_classifier=yes_medical,
        )
        return await agent.handle("i had an accident", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_start"
    assert outcome.flow_state["step"] == "safe"
    assert get_message("accident_safe_prompt", "en") in outcome.reply


def test_out_of_scope_message_in_yes_no_step_reprompts_step():
    async def intent_chat(message, language):
        return "chat"

    async def no_yesno(*args, **kwargs):
        return None

    session = _make_session(call_uuid="flow-oos")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}

    async def run():
        agent = FlowAgent(intent_classifier=intent_chat, yes_no_classifier=no_yesno)
        return await agent.handle("can you make pani puri", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert get_message("accident_drivable_prompt", "en") in outcome.reply


def test_claim_damage_free_text_not_blocked_by_guardrail():
    async def intent_chat(message, language):
        return "chat"

    async def flow_none(message, language):
        return "none"

    async def unknown_yes_no(*args, **kwargs):
        return None

    async def response_no(*args, **kwargs):
        return False

    session = _make_session(call_uuid="claim-damage-free-text")
    session.profile_loaded = True
    session.flow = {"name": "claim", "step": "damage_type", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            flow_classifier=flow_none,
            yes_no_classifier=unknown_yes_no,
            response_matcher=response_no,
        )
        return await agent.handle("full front part of car", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "claim_step"
    assert outcome.flow_state["name"] == "claim"
    assert outcome.flow_state["step"] == "description"
    assert get_message("claim_prompt_description", "en") in outcome.reply
    assert get_message("guardrail_scope", "en") not in outcome.reply


def test_claim_damage_free_text_not_detoured_by_flow_hint():
    async def intent_chat(message, language):
        return "chat"

    async def flow_accident(message, language):
        return "accident"

    async def unknown_yes_no(*args, **kwargs):
        return None

    async def response_no(*args, **kwargs):
        return False

    session = _make_session(call_uuid="claim-damage-no-detour")
    session.profile_loaded = True
    session.flow = {"name": "claim", "step": "damage_type", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            flow_classifier=flow_accident,
            yes_no_classifier=unknown_yes_no,
            response_matcher=response_no,
        )
        return await agent.handle("full front part of car", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "claim_step"
    assert outcome.flow_state["name"] == "claim"
    assert outcome.flow_state["step"] == "description"
    assert get_message("claim_prompt_description", "en") in outcome.reply
    assert get_message("guardrail_scope", "en") not in outcome.reply
    assert get_message("accident_empathy", "en") not in outcome.reply


def test_drivable_descriptive_response_does_not_trigger_guardrail():
    async def intent_chat(message, language):
        return "chat"

    async def yes_no_unknown(*args, **kwargs):
        return None

    async def response_relevant(*args, **kwargs):
        return True

    session = _make_session(call_uuid="drivable-descriptive")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            yes_no_classifier=yes_no_unknown,
            response_matcher=response_relevant,
        )
        return await agent.handle("it was started but wheel are not moving", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert get_message("guardrail_scope", "en") not in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply


def test_yes_short_affirmation_is_accepted():
    async def intent_chat(message, language):
        return "chat"

    async def yes_no(message, context, language):
        return True if context == "drivable" else None

    async def response_match(message, prompt, language):
        return True

    session = _make_session(call_uuid="short-yes")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            yes_no_classifier=yes_no,
            response_matcher=response_match,
        )
        return await agent.handle("yha", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"


def test_find_other_hospital_returns_next_result(monkeypatch):
    async def route_hospital(message, language):
        return "hospital"

    async def intent_chat(message, language):
        return "chat"

    async def yes_no(*args, **kwargs):
        return None

    async def response_match(*args, **kwargs):
        return True

    async def no_sms(*args, **kwargs):
        return False

    def fake_search_hospitals(query):
        return [
            {
                "name": "Preeti Urology & Kidney Hospital",
                "address": "Mig-1, 307, Road No. 4, Kphb Colony",
                "phone": "04023152444",
            },
            {
                "name": "Amor Hospitals",
                "address": "Balanagar Metro Station, Y Junction, Kukatpally",
                "phone": "04066069999",
            },
        ]

    monkeypatch.setattr("bot.application.flows.send_sms_async", no_sms)
    monkeypatch.setattr("bot.application.flows.search_hospitals", fake_search_hospitals)

    session = _make_session(call_uuid="hospital-next")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}
    session.last_location_query = "kphb"
    session.last_service = "hospital"
    session.last_hospital_name = "Preeti Urology & Kidney Hospital"

    async def run():
        agent = FlowAgent(
            flow_classifier=route_hospital,
            intent_classifier=intent_chat,
            yes_no_classifier=yes_no,
            response_matcher=response_match,
        )
        return await agent.handle("find other hospital", session, "en")

    outcome = asyncio.run(run())
    assert "Amor Hospitals" in outcome.reply


def test_onboarding_pending_flow_set_and_resumed_after_selection():
    async def always_accident(message, language):
        return "accident"

    session = _make_session(call_uuid="onboarding-pending")
    session.profile_loaded = True
    session.flow = {"name": "onboarding", "step": "select_policy", "data": {}}
    session.policies = [
        {"policy_number": "POL-502", "vehicle_reg_number": "TN-09-EE-7777"},
        {"policy_number": "POL-501", "vehicle_reg_number": "TN-09-DD-6666"},
    ]

    async def run_first():
        agent = FlowAgent(flow_classifier=always_accident)
        return await agent.handle("i had an accident find me a nearby hospital kphb", session, "en")

    first = asyncio.run(run_first())
    assert first.intent == "onboarding"
    assert session.pending_flow == "accident"

    async def run_second():
        agent = FlowAgent(flow_classifier=always_accident)
        return await agent.handle("7777", session, "en")

    second = asyncio.run(run_second())
    assert second.intent == "accident_start"
    assert second.flow_state["name"] == "accident"


def test_hospital_followup_otherone_reuses_last_location(monkeypatch):
    async def route_to_hospital(message, language):
        return "hospital"

    async def no_location(message, language):
        return None

    async def no_sms(*args, **kwargs):
        return False

    def fake_search_hospitals(query):
        assert query == "kphb"
        return [
            {
                "name": "Preeti Urology & Kidney Hospital",
                "address": "Mig-1, 307, Road No. 4, Kphb Colony",
                "phone": "04023152444",
            }
        ]

    monkeypatch.setattr("bot.application.flows.send_sms_async", no_sms)
    monkeypatch.setattr("bot.application.flows.search_hospitals", fake_search_hospitals)

    session = _make_session(call_uuid="hospital-otherone")
    session.profile_loaded = True
    session.last_service = "hospital"
    session.last_location_query = "kphb"

    async def run():
        agent = FlowAgent(flow_classifier=route_to_hospital, location_extractor=no_location)
        return await agent.handle("find me otherone", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "hospital_complete"
    assert "Nearest hospital" in outcome.reply
    assert "roadside" not in outcome.reply.lower()


def test_accident_medical_with_location_query_fetches_hospital(monkeypatch):
    async def yes_medical(message, context, language):
        return True if context == "medical" else None

    async def location_extract(message, language):
        return "kphb"

    async def no_sms(*args, **kwargs):
        return False

    def fake_search_hospitals(query):
        assert query == "kphb"
        return [
            {
                "name": "Preeti Urology & Kidney Hospital",
                "address": "Mig-1, 307, Road No. 4, Kphb Colony",
                "phone": "04023152444",
            }
        ]

    monkeypatch.setattr("bot.application.flows.send_sms_async", no_sms)
    monkeypatch.setattr("bot.application.flows.search_hospitals", fake_search_hospitals)

    session = _make_session(call_uuid="accident-medical-location")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "medical", "data": {}}

    async def run():
        agent = FlowAgent(yes_no_classifier=yes_medical, location_extractor=location_extract)
        return await agent.handle("find an hospital near kphb", session, "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "drivable"
    assert "Nearest hospital" in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply


def test_accident_drivable_vehicle_stopped_treated_as_not_drivable():
    async def no_drivable(message, context, language):
        return False if context == "drivable" else None

    session = _make_session(call_uuid="accident-drivable-stopped")
    session.selected_policy = "POL-501"
    session.policies = [{"policy_number": "POL-501", "rsa_covered": True}]
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}

    async def run():
        agent = FlowAgent(yes_no_classifier=no_drivable)
        return await agent.handle("vehicle stopped working", session, "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "rsa_consent"
    assert get_message("accident_rsa_offer_eligible", "en") in outcome.reply


def test_flow_agent_accident_drivable_skips_detour_for_vehicle_stopped():
    async def always_roadside(message, language):
        return "roadside"

    async def no_drivable(message, context, language):
        return False if context == "drivable" else None

    session = _make_session(call_uuid="flow-agent-drivable")
    session.profile_loaded = True
    session.selected_policy = "POL-501"
    session.policies = [{"policy_number": "POL-501", "rsa_covered": True}]
    session.flow = {"name": "accident", "step": "drivable", "data": {}}

    async def run():
        agent = FlowAgent(flow_classifier=always_roadside, yes_no_classifier=no_drivable)
        return await agent.handle("vehicle stopped working", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert get_message("accident_rsa_offer_eligible", "en") in outcome.reply
    assert get_message("roadside_prompt_have_vehicle", "en") not in outcome.reply


def test_accident_rsa_consent_yes_hinglish_goes_to_location():
    async def yes_rsa(message, context, language):
        return True if context == "rsa_consent" else None

    session = _make_session(call_uuid="rsa-consent-hinglish")
    session.selected_policy = "POL-501"
    session.policies = [{"policy_number": "POL-501", "rsa_covered": False}]
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "rsa_consent", "data": {"rsa_eligible": False}}

    async def run():
        agent = FlowAgent(yes_no_classifier=yes_rsa)
        return await agent.handle("yha", session, "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "rsa_location"
    assert get_message("roadside_location_prompt", "en") in outcome.reply


def test_hospital_followup_does_not_trigger_on_generic_yes():
    async def always_roadside(message, language):
        return "roadside"

    async def no_location(message, language):
        return None

    async def yes_rsa(message, context, language):
        return True if context == "rsa_consent" else None

    session = _make_session(call_uuid="hospital-followup-yes")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "rsa_consent", "data": {"rsa_eligible": False}}
    session.last_service = "hospital"
    session.last_location_query = "kphb"

    async def run():
        agent = FlowAgent(flow_classifier=always_roadside, location_extractor=no_location, yes_no_classifier=yes_rsa)
        return await agent.handle("yha", session, "en")

    outcome = asyncio.run(run())
    assert outcome.flow_state["step"] == "rsa_location"
    assert get_message("roadside_location_prompt", "en") in outcome.reply


def test_rsa_location_plain_locality_uses_roadside_not_hospital(monkeypatch):
    async def route_none(message, language):
        return "none"

    async def no_location(message, language):
        return None

    async def yes_no_unknown(*args, **kwargs):
        return None

    async def relevant_response(*args, **kwargs):
        return True

    def fake_search_garages(query):
        assert query == "aphb"
        return [
            {
                "name": "NEW RR MOTORS",
                "address": "APHB",
                "phone": "9440053357",
            }
        ]

    monkeypatch.setattr("bot.application.flows.search_garages", fake_search_garages)

    session = _make_session(call_uuid="rsa-location-raw")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "rsa_location", "data": {"rsa_eligible": False}}
    session.last_service = "hospital"

    async def run():
        agent = FlowAgent(
            flow_classifier=route_none,
            location_extractor=no_location,
            yes_no_classifier=yes_no_unknown,
            response_matcher=relevant_response,
        )
        return await agent.handle("aphb", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert "Arranged assistance" in outcome.reply
    assert "Nearest hospital" not in outcome.reply


def test_rsa_location_does_not_detour_to_hospital_without_explicit_intent(monkeypatch):
    async def route_none(message, language):
        return "none"

    async def location_extract(message, language):
        return "500071"

    async def yes_no_unknown(*args, **kwargs):
        return None

    def fake_search_garages(query):
        assert query == "Aphb 500071"
        return []

    monkeypatch.setattr("bot.application.flows.search_garages", fake_search_garages)

    session = _make_session(call_uuid="rsa-location-no-detour")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "rsa_location", "data": {"rsa_eligible": False}}
    session.last_service = "hospital"

    async def run():
        agent = FlowAgent(
            flow_classifier=route_none,
            location_extractor=location_extract,
            yes_no_classifier=yes_no_unknown,
        )
        return await agent.handle("Aphb 500071", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert get_message("garage_no_result", "en") in outcome.reply
    assert "hospital" not in outcome.reply.lower()


def test_accident_safe_injury_message_not_hijacked_by_hallucinated_location():
    async def intent_hospital_search(message, language):
        return "hospital_search"

    async def hallucinated_location(message, language):
        return "Karkhana"

    async def safe_is_no(message, context, language):
        return False if context == "safe" else None

    session = _make_session(call_uuid="safe-hallucinated-location")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "safe", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_hospital_search,
            location_extractor=hallucinated_location,
            yes_no_classifier=safe_is_no,
        )
        return await agent.handle("my leg is broken", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert outcome.flow_state["step"] == "medical"
    assert get_message("accident_medical_prompt", "en") in outcome.reply
    assert "Nearest hospital" not in outcome.reply


def test_explicit_hospital_detour_without_location_asks_for_location():
    async def intent_chat(message, language):
        return "chat"

    async def route_hospital(message, language):
        return "hospital"

    async def no_location(message, language):
        return None

    async def response_relevant(*args, **kwargs):
        return True

    session = _make_session(call_uuid="hospital-detour-no-location")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            flow_classifier=route_hospital,
            location_extractor=no_location,
            response_matcher=response_relevant,
        )
        return await agent.handle("find me a hospital", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "flow_detour"
    assert get_message("hospital_prompt_location", "en") in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply
    assert "Nearest hospital" not in outcome.reply


def test_roadside_request_not_hijacked_to_hospital_followup():
    async def intent_chat(message, language):
        return "chat"

    async def route_roadside(message, language):
        return "roadside"

    async def no_location(message, language):
        return None

    async def response_relevant(*args, **kwargs):
        return True

    session = _make_session(call_uuid="roadside-not-hospital")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "drivable", "data": {}}
    session.last_service = "hospital"
    session.last_location_query = "kphb"

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            flow_classifier=route_roadside,
            location_extractor=no_location,
            response_matcher=response_relevant,
        )
        return await agent.handle("find me road side assistance", session, "en")

    outcome = asyncio.run(run())
    assert "Nearest hospital" not in outcome.reply
    assert get_message("accident_drivable_prompt", "en") in outcome.reply


def test_yes_no_agent_unknown_not_treated_as_no(monkeypatch):
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeClient:
        def generate(self, messages, system_prompt):
            return _FakeResponse("UNKNOWN")

    monkeypatch.setattr("bot.application.orchestrator.build_client", lambda cfg: _FakeClient())
    agent = YesNoAgent(SETTINGS)
    result = asyncio.run(agent.classify("we are injured", "safe", "en"))
    assert result is None


def test_step_response_agent_unknown_not_treated_as_no(monkeypatch):
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeClient:
        def generate(self, messages, system_prompt):
            return _FakeResponse("UNKNOWN")

    monkeypatch.setattr("bot.application.orchestrator.build_client", lambda cfg: _FakeClient())
    agent = StepResponseAgent(SETTINGS)
    result = asyncio.run(agent.classify("aphb", "Share your location or pincode.", "en"))
    assert result is None


def test_accident_safe_semantic_no_does_not_trigger_guardrail():
    async def intent_chat(message, language):
        return "chat"

    async def yes_no_safe(message, context, language):
        return False if context == "safe" else None

    async def response_not_relevant(message, prompt, language):
        return False

    session = _make_session(call_uuid="accident-safe-semantic-no")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "safe", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            yes_no_classifier=yes_no_safe,
            response_matcher=response_not_relevant,
        )
        return await agent.handle("we are injured", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert outcome.flow_state["step"] == "medical"
    assert get_message("accident_medical_prompt", "en") in outcome.reply
    assert get_message("guardrail_scope", "en") not in outcome.reply


def test_accident_safe_semantic_fallback_advances_when_yesno_unknown():
    async def intent_chat(message, language):
        return "chat"

    async def route_hospital(message, language):
        return "hospital"

    async def yes_no_unknown(message, context, language):
        return None

    async def response_not_relevant(message, prompt, language):
        return False

    session = _make_session(call_uuid="accident-safe-fallback")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "safe", "data": {}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            flow_classifier=route_hospital,
            yes_no_classifier=yes_no_unknown,
            response_matcher=response_not_relevant,
        )
        return await agent.handle("we are injured", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert outcome.flow_state["step"] == "medical"
    assert get_message("accident_medical_prompt", "en") in outcome.reply
    assert get_message("guardrail_scope", "en") not in outcome.reply


def test_rsa_location_raw_locality_not_blocked_when_response_unknown(monkeypatch):
    async def intent_chat(message, language):
        return "chat"

    async def no_location(message, language):
        return None

    async def response_unknown(message, prompt, language):
        return None

    def fake_search_garages(query):
        assert query == "aphb"
        return [
            {
                "name": "NEW RR MOTORS",
                "address": "APHB",
                "phone": "9440053357",
            }
        ]

    monkeypatch.setattr("bot.application.flows.search_garages", fake_search_garages)

    session = _make_session(call_uuid="rsa-location-unknown")
    session.profile_loaded = True
    session.flow = {"name": "accident", "step": "rsa_location", "data": {"rsa_eligible": False}}

    async def run():
        agent = FlowAgent(
            intent_classifier=intent_chat,
            location_extractor=no_location,
            response_matcher=response_unknown,
        )
        return await agent.handle("aphb", session, "en")

    outcome = asyncio.run(run())
    assert outcome.intent == "accident_step"
    assert "Arranged assistance" in outcome.reply
    assert get_message("guardrail_scope", "en") not in outcome.reply


def test_intent_agent_label_parser_ignores_negated_substrings(monkeypatch):
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeClient:
        def generate(self, messages, system_prompt):
            return _FakeResponse("chat (not claim_payment)")

    monkeypatch.setattr("bot.application.orchestrator.build_client", lambda cfg: _FakeClient())
    agent = IntentAgent(SETTINGS)
    result = asyncio.run(agent.classify("i had an accident", "en"))
    assert result == "chat"


def test_flow_start_agent_label_parser_ignores_extra_text(monkeypatch):
    class _FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class _FakeClient:
        def generate(self, messages, system_prompt):
            return _FakeResponse("none (do not start any flow)")

    monkeypatch.setattr("bot.application.orchestrator.build_client", lambda cfg: _FakeClient())
    agent = FlowStartAgent(SETTINGS)
    result = asyncio.run(agent.classify("when will claim payment be processed", "en"))
    assert result == "none"
