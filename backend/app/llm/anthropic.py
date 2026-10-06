"""Anthropic LLM provider — stub implementation."""

from __future__ import annotations

import logging

import anthropic

from app.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) implementation via the anthropic SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text using the Anthropic API."""
        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            response = await self._client.messages.create(**kwargs)

            text = response.content[0].text if response.content else ""
            logger.info("Anthropic: generated %d chars", len(text))
            return text

        except Exception as e:
            logger.error("Anthropic generation error: %s", e)
            return f"[LLM Error] Could not generate synthesis: {e}"
