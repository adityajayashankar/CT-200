from __future__ import annotations

import os
from typing import Protocol

import httpx


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class LLMConfigurationError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Minimal client for Groq, OpenRouter, or another OpenAI-compatible API."""

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
        self.model = os.getenv("LLM_MODEL")

    def complete(self, prompt: str) -> str:
        if not self.api_key or not self.model:
            raise LLMConfigurationError("LLM_API_KEY and LLM_MODEL must be configured for generation")
        response = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": "Return only valid JSON; do not add markdown fences."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=45,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
