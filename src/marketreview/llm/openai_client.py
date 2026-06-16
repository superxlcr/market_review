"""OpenAI-compatible LLM client (DeepSeek, OpenAI, etc.)."""
import os
from openai import OpenAI

from marketreview.llm import LLMClient
from marketreview.log_util import get_logger

log = get_logger(__name__)


class OpenAIClient(LLMClient):
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com")
        # Normalize: ensure base_url ends with /v1
        if not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        self._model = os.environ.get("MODEL", "deepseek-chat")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        log.info("OpenAIClient init: model=%s base_url=%s", self._model, base_url)

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        log.info("LLM request: model=%s system_len=%d user_len=%d",
                 self._model, len(system_prompt), len(user_prompt))
        log.debug("LLM system_prompt: %s", system_prompt)
        log.debug("LLM user_prompt: %s", user_prompt)

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=16000,
            extra_body={
                "reasoning_effort": "max",
                "thinking": {"type": "enabled"},
            },
        )
        content = resp.choices[0].message.content.strip()
        log.info("LLM response: len=%d content=%s", len(content), content)
        return content
