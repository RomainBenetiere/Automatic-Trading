"""Abstract LLM provider interface and factory."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM text generation.

    All providers expose a single `generate()` method. The LLM is only
    used for narrative synthesis — never for computing indicators.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate text from a prompt.

        Args:
            prompt: the user/task prompt
            system_prompt: optional system-level instruction
            max_tokens: maximum response length

        Returns the generated text.
        """
        ...


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Factory — instantiate the configured LLM provider.

    Provider selection is driven by the `LLM_PROVIDER` env var.
    """
    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings

    provider_name = settings.llm_provider.lower()

    if provider_name == "gemini":
        from app.llm.gemini import GeminiProvider
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.llm_model,
        )
    elif provider_name == "openai":
        from app.llm.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
        )
    elif provider_name == "anthropic":
        from app.llm.anthropic import AnthropicProvider
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
