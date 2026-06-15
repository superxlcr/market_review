"""
LLM abstraction layer. Hides vendor differences behind a single interface.
"""
from abc import ABC, abstractmethod
import os


class LLMClient(ABC):
    """Unified interface for LLM API calls."""

    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat request and return the response text."""


def create_llm_client() -> LLMClient:
    """Factory: return an LLMClient based on LLM_PROVIDER env var.

    Supported providers: 'openai' (default, covers DeepSeek/OpenAI/any
    OpenAI-compatible endpoint).
    """
    # Import here to avoid circular imports at module level
    from marketreview.llm.openai_client import OpenAIClient
    return OpenAIClient()
