"""OpenAI LLM provider — stub implementation."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI implementation via the openai SDK."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text using the OpenAI API."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
            }
            if not self.model.startswith(("o1", "o3")):
                kwargs["temperature"] = 0.4

            try:
                response = await self._client.chat.completions.create(**kwargs)
            except Exception as e:
                err_str = str(e).lower()
                # If model prefers legacy max_tokens
                if "max_completion_tokens" in err_str:
                    kwargs.pop("max_completion_tokens", None)
                    kwargs["max_tokens"] = max_tokens
                    response = await self._client.chat.completions.create(**kwargs)
                # If model doesn't support temperature (like o1 / o3)
                elif "temperature" in err_str:
                    kwargs.pop("temperature", None)
                    response = await self._client.chat.completions.create(**kwargs)
                else:
                    raise

            text = response.choices[0].message.content or ""
            logger.info("OpenAI: generated %d chars", len(text))
            return text

        except Exception as e:
            logger.error("OpenAI generation error: %s", e)
            return f"[LLM Error] Could not generate synthesis: {e}"
