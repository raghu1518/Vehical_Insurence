from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import requests

from .config import LLMSettings


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any] | None = None


class LLMError(Exception):
    pass


class BaseLLMClient:
    def __init__(self, settings: LLMSettings):
        self.settings = settings

    def generate(self, messages: list[dict], system_prompt: str | None) -> LLMResponse:
        raise NotImplementedError


class OpenAICompatibleClient(BaseLLMClient):
    DEFAULT_URLS = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
    }

    def generate(self, messages: list[dict], system_prompt: str | None) -> LLMResponse:
        url = self.settings.base_url or self.DEFAULT_URLS.get(self.settings.provider, "")
        if not url:
            raise LLMError("No base URL configured for provider.")

        payload_messages = list(messages)
        if system_prompt:
            payload_messages = [{"role": "system", "content": system_prompt}] + payload_messages

        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        payload = {
            "model": self.settings.model,
            "messages": payload_messages,
            "temperature": 0.3,
            "stream": False,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.settings.timeout_s)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LLMError(str(exc)) from exc

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise LLMError("Empty response from LLM provider.")
        return LLMResponse(content=content, raw=data)


class OllamaClient(BaseLLMClient):
    def generate(self, messages: list[dict], system_prompt: str | None) -> LLMResponse:
        base_url = self.settings.base_url or "http://localhost:11434"
        url = base_url.rstrip("/") + "/api/chat"

        payload_messages = list(messages)
        if system_prompt:
            payload_messages = [{"role": "system", "content": system_prompt}] + payload_messages

        payload = {
            "model": self.settings.model,
            "messages": payload_messages,
            "stream": False,
        }

        try:
            response = requests.post(url, json=payload, timeout=self.settings.timeout_s)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LLMError(str(exc)) from exc

        content = ""
        if isinstance(data, dict):
            if "message" in data and isinstance(data["message"], dict):
                content = data["message"].get("content", "")
            elif "response" in data:
                content = data.get("response", "")

        if not content:
            raise LLMError("Empty response from Ollama.")
        return LLMResponse(content=content, raw=data)


class ClaudeClient(BaseLLMClient):
    DEFAULT_URL = "https://api.anthropic.com/v1/messages"

    def generate(self, messages: list[dict], system_prompt: str | None) -> LLMResponse:
        url = self.settings.base_url or self.DEFAULT_URL
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.settings.api_key:
            headers["x-api-key"] = self.settings.api_key

        payload = {
            "model": self.settings.model,
            "max_tokens": 512,
            "messages": messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.settings.timeout_s)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise LLMError(str(exc)) from exc

        content_blocks = data.get("content", [])
        content = ""
        if content_blocks and isinstance(content_blocks, list):
            content = "".join(block.get("text", "") for block in content_blocks if isinstance(block, dict))

        if not content:
            raise LLMError("Empty response from Claude.")
        return LLMResponse(content=content, raw=data)


class MockClient(BaseLLMClient):
    def generate(self, messages: list[dict], system_prompt: str | None) -> LLMResponse:
        last = messages[-1]["content"] if messages else ""
        content = f"[Mock LLM] {last}"
        return LLMResponse(content=content, raw={"mock": True})


def build_client(settings: LLMSettings) -> BaseLLMClient:
    provider = settings.provider.lower()
    if provider in {"openai", "groq"}:
        return OpenAICompatibleClient(settings)
    if provider == "ollama":
        return OllamaClient(settings)
    if provider == "claude":
        return ClaudeClient(settings)
    return MockClient(settings)
