from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from bot.infrastructure.config import Settings
from bot.shared.datetime_parser import ParsedDateTime
from bot.shared.i18n import detect_language, get_message
from bot.infrastructure.llm_clients import build_client, LLMError
from bot.application.flows import FlowAgent
from bot.infrastructure.rag import get_retriever
from bot.shared.translator import translate_text
from bot.shared.guardrails import apply_guardrails, is_prompt_disclosure_request
from bot.shared.tools import (
    ToolResult,
    parse_add_event,
    parse_remove_event,
    tool_calendar_add,
    tool_calendar_list,
    tool_calendar_remove,
    tool_claim_payment,
    tool_greeting,
    tool_garage_search,
    tool_hospital_search,
    tool_sendoff,
    tool_time,
)


@dataclass
class AgentResult:
    reply: str
    language: str
    intent: str
    used_tool: str | None = None
    tool_data: dict[str, Any] | None = None
    flow_state: dict[str, Any] | None = None
    chat_ended: bool = False


class LanguageAgent:
    def detect(self, message: str, current_language: str, default_language: str) -> str:
        return detect_language(message, current_language, default_language)


class IntentAgent:
    INTENT_LABELS = [
        "greeting",
        "sendoff",
        "no_more_help",
        "help_options",
        "time",
        "hospital_search",
        "garage_search",
        "calendar_add",
        "calendar_list",
        "calendar_remove",
        "claim_payment",
        "chat",
        "faq",
    ]

    def __init__(self, settings: Settings) -> None:
        self.client = build_client(settings.llm)

    def _extract_label(self, raw: str) -> str:
        text = (raw or "").strip().lower()
        if not text:
            return "chat"
        if text in self.INTENT_LABELS:
            return text
        for token in re.findall(r"[a-z_]+", text):
            if token in self.INTENT_LABELS:
                return token
        return "chat"

    async def classify(self, message: str, language: str) -> str:
        prompt = (
            "You are an intent classifier for a multilingual support assistant.\n"
            f"Return ONLY one label from: {', '.join(self.INTENT_LABELS)}.\n"
            "If the message is not clearly a tool request, return chat.\n"
            "claim_payment is ONLY for questions about claim payment status/timeline/settlement.\n"
            "If the user is reporting an accident, asking for hospital/ambulance, roadside/towing, or filing a claim, return chat.\n"
            "Examples:\n"
            "- \"I had an accident\" -> chat\n"
            "- \"Need a hospital near KPHB\" -> hospital_search\n"
            "- \"Tow truck needed\" -> roadside_search\n"
            "- \"When will my claim payment be processed?\" -> claim_payment\n"
            f"User language: {language}.\n"
            f"Message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate,
                [{"role": "user", "content": prompt}],
                None,
            )
            raw = response.content
        except LLMError:
            return "chat"
        return self._extract_label(raw)


class ToolAgent:
    def run(self, intent: str, message: str, language: str) -> ToolResult | None:
        if intent == "greeting":
            return tool_greeting(language)
        if intent == "sendoff":
            return tool_sendoff(language)
        if intent == "time":
            return tool_time(language)
        if intent == "hospital_search":
            return tool_hospital_search(message, language)
        if intent == "garage_search":
            return tool_garage_search(message, language)
        if intent == "calendar_add":
            payload = parse_add_event(message)
            if not payload:
                return None
            return tool_calendar_add(payload["title"], payload["date"], payload.get("time"), language)
        if intent == "calendar_list":
            return tool_calendar_list(language)
        if intent == "calendar_remove":
            title = parse_remove_event(message)
            if not title:
                return None
            return tool_calendar_remove(title, language)
        if intent == "claim_payment":
            return tool_claim_payment(language)
        return None


class ChatAgent:
    def __init__(self, settings: Settings):
        self.client = build_client(settings.llm)

    async def respond(self, messages: list[dict], system_prompt: str | None) -> str:
        response = await asyncio.to_thread(self.client.generate, messages, system_prompt)
        return response.content.strip()


class YesNoAgent:
    def __init__(self, settings: Settings):
        self.client = build_client(settings.llm)

    async def classify(self, message: str, context: str, language: str) -> bool | None:
        prompt = (
            "You are a strict classifier. Decide if the user's response means YES or NO.\n"
            "Return only one token: YES, NO, or UNKNOWN.\n"
            "Use meaning, not keyword overlap.\n"
            "Context rules:\n"
            "- safe: YES means everyone is safe; NO means unsafe/injured.\n"
            "- medical: YES means medical help is needed; NO means not needed.\n"
            "- drivable: YES means vehicle can be driven; NO means cannot move/start.\n"
            "- rsa_consent/claim_consent/fir: YES means user agrees/provided; NO means user declines/not provided.\n"
            "Examples:\n"
            "- safe + 'we are injured' -> NO\n"
            "- safe + 'my leg is broken' -> NO\n"
            "- medical + 'need ambulance' -> YES\n"
            "- medical + 'of course' -> YES\n"
            "- medical + 'yha' -> YES\n"
            "- drivable + 'wheel not moving' -> NO\n"
            "- drivable + 'vehicle not starting' -> NO\n"
            "- drivable + 'need roadside assistance' -> NO\n"
            "- drivable + 'car is drivable' -> YES\n"
            f"Context: {context}.\n"
            f"User message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate, [{"role": "user", "content": prompt}], None
            )
        except LLMError:
            return None
        text = response.content.strip().upper()
        for token in re.findall(r"[A-Z]+", text):
            if token == "YES":
                return True
            if token == "NO":
                return False
            if token == "UNKNOWN":
                return None
        return None


class StepResponseAgent:
    def __init__(self, settings: Settings):
        self.client = build_client(settings.llm)

    async def classify(self, message: str, prompt: str, language: str) -> bool | None:
        if not prompt:
            return None
        query = (
            "You are a response relevance classifier.\n"
            "Determine if the user's message is answering the question.\n"
            "Return ONLY YES, NO, or UNKNOWN.\n"
            "Use meaning, not keyword overlap.\n"
            "If the question expects a yes/no answer and the user gives a short affirmation/negation"
            " (e.g., yes/no/yeah/yha/haan/nah), return YES.\n"
            "If the user gives a semantic answer to a yes/no question, return YES.\n"
            "Examples:\n"
            "- Question: 'Is everyone safe?' User: 'we are injured' -> YES\n"
            "- Question: 'Is your vehicle drivable?' User: 'wheel not moving' -> YES\n"
            f"Question: {prompt}\n"
            f"User message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate, [{"role": "user", "content": query}], None
            )
        except LLMError:
            return None
        text = response.content.strip().upper()
        for token in re.findall(r"[A-Z]+", text):
            if token == "YES":
                return True
            if token == "NO":
                return False
            if token == "UNKNOWN":
                return None
        return None


class LocationAgent:
    def __init__(self, settings: Settings):
        self.client = build_client(settings.llm)

    async def extract(self, message: str, language: str) -> str | None:
        prompt = (
            "Extract the location, locality, or pincode from the user message.\n"
            "Return ONLY the location string. If no location is present, return NONE.\n"
            f"User language: {language}\n"
            f"Message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate, [{"role": "user", "content": prompt}], None
            )
        except LLMError:
            return None
        raw = response.content.strip()
        if not raw:
            return None
        if raw.strip().upper() == "NONE":
            return None
        return raw


class DateTimeAgent:
    def __init__(self, settings: Settings):
        self.client = build_client(settings.llm)

    async def parse(self, message: str, language: str, now: datetime) -> ParsedDateTime | None:
        prompt = (
            "Extract the incident datetime from the user message.\n"
            "Return ONLY one of:\n"
            "1) JSON object: {\"datetime\":\"YYYY-MM-DDTHH:MM:SS\",\"had_time\":true|false}\n"
            "2) NONE\n"
            "Rules:\n"
            "- Resolve relative expressions (e.g., yesterday, last night) using the provided reference datetime.\n"
            "- If time is not explicitly present, use 00:00:00 and had_time=false.\n"
            "- Do not add explanations.\n"
            f"Reference datetime: {now.isoformat()}\n"
            f"User language: {language}\n"
            f"Message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate,
                [{"role": "user", "content": prompt}],
                None,
            )
            raw = response.content.strip()
        except LLMError:
            return None
        if not raw or raw.upper() == "NONE":
            return None

        payload_text = raw
        if "{" in raw and "}" in raw:
            payload_text = raw[raw.find("{") : raw.rfind("}") + 1]
        try:
            payload = json.loads(payload_text)
        except Exception:
            return None

        value = str(payload.get("datetime", "")).strip()
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None and now.tzinfo is not None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        had_time = bool(payload.get("had_time", False))
        return ParsedDateTime(value=parsed, had_time=had_time)

class FaqAgent:
    def __init__(self) -> None:
        self.retriever = get_retriever()

    def answer(self, message: str, language: str) -> str | None:
        if not message.strip():
            return None
        if "?" not in message and len(message.split()) < 3:
            return None
        results = self.retriever.query(message, top_k=1)
        if not results:
            return None
        top = results[0]
        if top.get("score", 0.0) < 0.15:
            return None
        text = str(top.get("text", "")).strip()
        if not text:
            return None
        if language != "en":
            return translate_text(text, language)
        return text


class FlowStartAgent:
    LABELS = ["accident", "hospital", "roadside", "claim", "none"]

    def __init__(self, settings: Settings) -> None:
        self.client = build_client(settings.llm)

    def _extract_label(self, raw: str) -> str:
        text = (raw or "").strip().lower()
        if not text:
            return "none"
        if text in self.LABELS:
            return text
        for token in re.findall(r"[a-z_]+", text):
            if token in self.LABELS:
                return token
        return "none"

    async def classify(self, message: str, language: str) -> str | None:
        prompt = (
            "You are a flow router for an insurance support assistant.\n"
            f"Return ONLY one label from: {', '.join(self.LABELS)}.\n"
            "Use the user's meaning, not keywords.\n"
            "Pick:\n"
            "- accident: user mentions an accident/crash/collision (even if they also ask for a hospital)\n"
            "- hospital: user needs medical help or hospital/ambulance and does NOT mention an accident\n"
            "- roadside: vehicle breakdown, towing, puncture, battery, pickup\n"
            "- claim: wants to file or continue a claim\n"
            "- none: general chat or unclear\n"
            "Examples:\n"
            "- \"I had an accident and need a hospital\" -> accident\n"
            "- \"I had an accident\" -> accident\n"
            "- \"Need a hospital near KPHB\" -> hospital\n"
            "- \"My car broke down, need towing\" -> roadside\n"
            "- \"I want to file a claim\" -> claim\n"
            "- \"When will my claim payment be processed?\" -> none\n"
            f"User language: {language}\n"
            f"Message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate,
                [{"role": "user", "content": prompt}],
                None,
            )
            raw = response.content
        except LLMError:
            return None
        return self._extract_label(raw)


class CustomerTypeAgent:
    LABELS = ["new", "existing", "unknown"]

    def __init__(self, settings: Settings) -> None:
        self.client = build_client(settings.llm)

    async def classify(self, message: str, language: str) -> str | None:
        prompt = (
            "You are a customer type classifier for an insurance assistant.\n"
            f"Return ONLY one label from: {', '.join(self.LABELS)}.\n"
            "Decide if the user says they are a NEW customer, an EXISTING customer, or UNKNOWN.\n"
            f"User language: {language}\n"
            f"Message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate,
                [{"role": "user", "content": prompt}],
                None,
            )
            raw = response.content.strip().lower()
        except LLMError:
            return "unknown"

        if raw in self.LABELS:
            return raw
        for label in self.LABELS:
            if label in raw:
                return label
        return "unknown"


class BuyPolicyAgent:
    LABELS = ["buy_policy", "other"]

    def __init__(self, settings: Settings) -> None:
        self.client = build_client(settings.llm)

    async def classify(self, message: str, language: str) -> bool | None:
        prompt = (
            "You are an intent classifier.\n"
            f"Return ONLY one label from: {', '.join(self.LABELS)}.\n"
            "Buy_policy means the user wants to purchase or inquire about buying an insurance policy.\n"
            "Other means anything else.\n"
            f"User language: {language}\n"
            f"Message: {message}"
        )
        try:
            response = await asyncio.to_thread(
                self.client.generate,
                [{"role": "user", "content": prompt}],
                None,
            )
            raw = response.content.strip().lower()
        except LLMError:
            return None

        if "buy_policy" in raw:
            return True
        if "other" in raw:
            return False
        return None


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.language_agent = LanguageAgent()
        self.intent_agent = IntentAgent(settings)
        self.tool_agent = ToolAgent()
        self.yes_no_agent = YesNoAgent(settings)
        self.step_response_agent = StepResponseAgent(settings)
        self.flow_start_agent = FlowStartAgent(settings)
        self.customer_type_agent = CustomerTypeAgent(settings)
        self.buy_policy_agent = BuyPolicyAgent(settings)
        self.location_agent = LocationAgent(settings)
        self.datetime_agent = DateTimeAgent(settings)
        self.flow_agent = FlowAgent(
            yes_no_classifier=self.yes_no_agent.classify,
            flow_classifier=self.flow_start_agent.classify,
            customer_type_classifier=self.customer_type_agent.classify,
            buy_policy_classifier=self.buy_policy_agent.classify,
            intent_classifier=self.intent_agent.classify,
            location_extractor=self.location_agent.extract,
            response_matcher=self.step_response_agent.classify,
            datetime_parser=self.datetime_agent.parse,
        )
        self.chat_agent = ChatAgent(settings)
        self.faq_agent = FaqAgent()

    async def handle(
        self,
        message: str,
        session: Any,
        prompts: list[dict],
    ) -> AgentResult:
        language = self.language_agent.detect(message, session.language, self.settings.default_language)

        if is_prompt_disclosure_request(message):
            return AgentResult(
                reply=get_message("guardrail_prompt", language),
                language=language,
                intent="guardrail_prompt",
                used_tool=None,
                tool_data=None,
                flow_state=None,
                chat_ended=False,
            )

        flow_outcome = await self.flow_agent.handle(message, session, language)
        if flow_outcome:
            return AgentResult(
                reply=flow_outcome.reply,
                language=language,
                intent=flow_outcome.intent,
                used_tool=None,
                tool_data=None,
                flow_state=flow_outcome.flow_state,
                chat_ended=flow_outcome.intent in {"assist_sendoff", "sendoff"},
            )

        intent = await self.intent_agent.classify(message, language)
        if intent == "no_more_help":
            reply = get_message("assist_sendoff", language)
            return AgentResult(
                reply=reply,
                language=language,
                intent="assist_sendoff",
                used_tool=None,
                tool_data=None,
                flow_state=None,
                chat_ended=True,
            )
        if intent == "help_options":
            reply = get_message("faq_can_do", language)
            return AgentResult(
                reply=reply,
                language=language,
                intent="faq_help_options",
                used_tool="faq",
                tool_data=None,
                flow_state=None,
            )
        tool_result = self.tool_agent.run(intent, message, language)

        if tool_result:
            return AgentResult(
                reply=tool_result.content,
                language=language,
                intent=intent,
                used_tool=tool_result.name,
                tool_data=tool_result.data,
                flow_state=None,
                chat_ended=(intent == "sendoff"),
            )

        if intent in {"chat", "faq"}:
            rag_answer = self.faq_agent.answer(message, language)
            if rag_answer:
                rag_answer = apply_guardrails(rag_answer, language)
                return AgentResult(
                    reply=rag_answer,
                    language=language,
                    intent="faq_rag",
                    used_tool="faq_rag",
                    tool_data=None,
                    flow_state=None,
                )

        _ = prompts
        return AgentResult(
            reply=get_message("guardrail_scope", language),
            language=language,
            intent="guardrail_scope",
            used_tool=None,
            tool_data=None,
            flow_state=None,
            chat_ended=False,
        )
