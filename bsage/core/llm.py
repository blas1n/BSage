"""LiteLLM client — unified LLM interface via litellm.acompletion."""

from __future__ import annotations

import litellm
import structlog

logger = structlog.get_logger(__name__)


class LiteLLMClient:
    """Wrapper around litellm.acompletion for clean abstraction and testability."""

    def __init__(
        self,
        model: str,
        api_key: str = "",
        api_base: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._api_base = api_base

    async def chat(self, system: str, messages: list[dict]) -> str:
        """Send a chat completion request via litellm.

        Args:
            system: System prompt.
            messages: List of message dicts (role + content).

        Returns:
            The assistant's response text.
        """
        full_messages = [{"role": "system", "content": system}, *messages]

        kwargs: dict = {
            "model": self._model,
            "messages": full_messages,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base

        logger.info("llm_request", model=self._model, message_count=len(full_messages))

        response = await litellm.acompletion(**kwargs)

        if not response.choices:
            raise RuntimeError("LLM returned empty choices")

        text = response.choices[0].message.content

        logger.info("llm_response", model=self._model, length=len(text))
        return text
