"""Gemini LLM provider — default production implementation."""

from __future__ import annotations

import logging

from google import genai

from app.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Google Gemini implementation via the google-genai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text using the Gemini API."""
        try:
            config = genai.types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.4,  # Low temperature for factual synthesis
            )
            if system_prompt:
                config.system_instruction = system_prompt

            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )

            text = response.text or ""
            logger.info("Gemini: generated %d chars", len(text))
            return text

        except Exception as e:
            logger.error("Gemini generation error: %s", e)
            return f"[LLM Error] Could not generate synthesis: {e}"
