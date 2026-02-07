from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from bot.infrastructure.config import Settings
from bot.shared.i18n import detect_language, get_message, matches_intent
from bot.infrastructure.llm_clients import build_client, LLMError
from bot.application.flows import FlowAgent
from bot.infrastructure.rag import get_retriever
from bot.shared.translator import translate_text
from bot.shared.system_prompts import select_prompt_for_language
from bot.shared.guardrails import apply_guardrails
from bot.shared.tools import (
    ToolResult,
    parse_add_event,
    parse_remove_event,
    tool_calendar_add,
    tool_calendar_list,
    tool_calendar_remove,
    tool_claim_payment,
    tool_faq,
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
        "time",
        "hospital_search",
        "garage_search",
        "calendar_add",
        "calendar_list",
        "calendar_remove",
        "claim_payment",
        "faq",
        "chat",
    ]

    def __init__(self, settings: Settings) -> None:
        self.client = build_client(settings.llm)

    async def classify(self, message: str, language: str) -> str:
        prompt = (
            "You are an intent classifier for a multilingual support assistant.\n"
            f"Return ONLY one label from: {', '.join(self.INTENT_LABELS)}.\n"
            "If the message is not clearly a tool request, return chat.\n"
            f"User language: {language}.\n"
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
            return "chat"

        for label in self.INTENT_LABELS:
            if raw == label:
                return label

        for label in self.INTENT_LABELS:
            if label in raw:
                return label

        if "calendar" in raw:
            return "calendar_list"
        if "hospital" in raw:
            return "hospital_search"
        if "garage" in raw or "workshop" in raw:
            return "garage_search"
        if "time" in raw:
            return "time"
        if "claim" in raw and "payment" in raw:
            return "claim_payment"
        if "greet" in raw or "hello" in raw:
            return "greeting"
        if "bye" in raw or "goodbye" in raw:
            return "sendoff"
        if "faq" in raw:
            return "faq"
        return "chat"


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
        if intent == "faq":
            return tool_faq(message, language)
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
        if "YES" in text:
            return True
        if "NO" in text:
            return False
        return None

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

    async def classify(self, message: str, language: str) -> str | None:
        prompt = (
            "You are a flow router for an insurance support assistant.\n"
            f"Return ONLY one label from: {', '.join(self.LABELS)}.\n"
            "Use the user's meaning, not keywords.\n"
            "Pick:\n"
            "- accident: user mentions an accident/crash/collision\n"
            "- hospital: user needs medical help or hospital/ambulance\n"
            "- roadside: vehicle breakdown, towing, puncture, battery, pickup\n"
            "- claim: wants to file or continue a claim\n"
            "- none: general chat or unclear\n"
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

        if raw in self.LABELS:
            return raw

        for label in self.LABELS:
            if label in raw:
                return label

        return "none"


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
        self.flow_start_agent = FlowStartAgent(settings)
        self.customer_type_agent = CustomerTypeAgent(settings)
        self.buy_policy_agent = BuyPolicyAgent(settings)
        self.flow_agent = FlowAgent(
            yes_no_classifier=self.yes_no_agent.classify,
            flow_classifier=self.flow_start_agent.classify,
            customer_type_classifier=self.customer_type_agent.classify,
            buy_policy_classifier=self.buy_policy_agent.classify,
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
        flow_outcome = await self.flow_agent.handle(message, session, language)
        if flow_outcome:
            return AgentResult(
                reply=flow_outcome.reply,
                language=language,
                intent=flow_outcome.intent,
                used_tool=None,
                tool_data=None,
                flow_state=flow_outcome.flow_state,
            )

        if not message.strip() or matches_intent(message, "no_more_help"):
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

        if matches_intent(message, "claim_payment"):
            tool_result = tool_claim_payment(language)
            return AgentResult(
                reply=tool_result.content,
                language=language,
                intent="claim_payment",
                used_tool=tool_result.name,
                tool_data=tool_result.data,
                flow_state=None,
            )

        if matches_intent(message, "help_options"):
            reply = get_message("faq_can_do", language)
            return AgentResult(
                reply=reply,
                language=language,
                intent="faq_help_options",
                used_tool="faq",
                tool_data=None,
                flow_state=None,
            )

        intent = await self.intent_agent.classify(message, language)
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

        if intent == "chat":
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

        system_prompt = None
        prompt = select_prompt_for_language(prompts, session.system_prompt_id, language)
        if prompt:
            system_prompt = prompt.get("prompt")

        messages = list(session.history) + [{"role": "user", "content": message}]
        try:
            reply = await self.chat_agent.respond(messages, system_prompt)
        except LLMError:
            reply = (
                "LLM उपलब्ध नहीं है। कृपया कॉन्फ़िगरेशन जाँचें।"
                if language == "hi"
                else "LLM is unavailable. Please check the configuration."
            )

        reply = apply_guardrails(reply, language)
        return AgentResult(
            reply=reply,
            language=language,
            intent=intent,
            used_tool=None,
            tool_data=None,
            flow_state=None,
        )
