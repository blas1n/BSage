"""LiteLLM client — unified LLM interface via litellm.acompletion."""

from __future__ import annotations

from typing import TYPE_CHECKING

import litellm
import structlog

if TYPE_CHECKING:
    from bsage.core.runtime_config import RuntimeConfig

logger = structlog.get_logger(__name__)


class LiteLLMClient:
    """Wrapper around litellm.acompletion that reads config per-call.

    Holds a reference to a RuntimeConfig instance so that LLM model,
    API key, and API base can be changed at runtime without restart.
    """

    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._config = runtime_config

    async def chat(self, system: str, messages: list[dict]) -> str:
        """Send a chat completion request via litellm.

        Reads model/key/base from RuntimeConfig on every call so that
        runtime changes take effect immediately.

        Args:
            system: System prompt.
            messages: List of message dicts (role + content).

        Returns:
            The assistant's response text.
        """
        model = self._config.llm_model
        api_key = self._config.llm_api_key
        api_base = self._config.llm_api_base

        full_messages = [{"role": "system", "content": system}, *messages]

        kwargs: dict = {
            "model": model,
            "messages": full_messages,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        logger.info("llm_request", model=model, message_count=len(full_messages))

        response = await litellm.acompletion(**kwargs)

        if not response.choices:
            raise RuntimeError("LLM returned empty choices")

        text = response.choices[0].message.content

        logger.info("llm_response", model=model, length=len(text))
        return text
