"""LiteLLMClient — high-level chat + tool-loop adapter on top of bsvibe-llm.

The BSage entry point for all LLM completions. Owns the system-prompt /
tool-loop semantics that BSage skills expect; defers the actual vendor
call to :class:`bsvibe_llm.LlmClient` so retry, fallback, run-audit
metadata, and provider-aware reasoning suppression live in one place
(shared with BSNexus, BSGateway, etc).

Direct ``litellm`` usage is intentionally absent here — see
``bsage/garden/embedder.py`` (embedding-only) and
``bsage/garden/ingest_compiler.py`` (model registry lookup) for the only
remaining call sites, both of which use litellm primitives that
``bsvibe-llm`` does not (yet) wrap.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from bsvibe_llm import LlmClient, LlmSettings, RunAuditMetadata
from litellm.types.utils import Message

from bsage.core.skill_context import ToolHandler

if TYPE_CHECKING:
    from bsage.core.runtime_config import RuntimeConfig

logger = structlog.get_logger(__name__)


class LiteLLMClient:
    """High-level chat client backed by ``bsvibe_llm.LlmClient``.

    Holds a reference to a RuntimeConfig instance so model, API key, base
    URL, and gateway URL can change at runtime without restart — settings
    are rebuilt per call.
    """

    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._config = runtime_config

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_handler: ToolHandler | None = None,
        max_rounds: int = 10,
        suppress_reasoning: bool = False,
    ) -> str:
        """Send a chat completion, optionally running a tool-use loop.

        Args:
            system: System prompt.
            messages: List of message dicts (role + content).
            tools: Optional OpenAI-format tool definitions.
            tool_handler: Optional async callback (tool_call_id, name, args) -> result JSON.
            max_rounds: Max tool-use round-trips (only used with tools).
            suppress_reasoning: When True, disable chain-of-thought for
                reasoning-capable providers (Anthropic extended thinking,
                OpenAI o-series, Ollama reasoning models, mlx-lm/vllm).
                Compile-time call sites that want short structured output
                should set this.
        """
        work_messages = [{"role": "system", "content": system}, *messages]

        if not tools or not tool_handler:
            logger.info(
                "llm_request",
                model=self._config.llm_model,
                message_count=len(work_messages),
                suppress_reasoning=suppress_reasoning,
            )
            msg = await self._complete(work_messages, suppress_reasoning=suppress_reasoning)
            text = msg.content or ""
            logger.info("llm_response", model=self._config.llm_model, length=len(text))
            return text

        for round_num in range(max_rounds):
            logger.info(
                "llm_tool_request",
                model=self._config.llm_model,
                round=round_num,
                message_count=len(work_messages),
            )
            assistant_msg = await self._complete(
                work_messages, tools=tools, suppress_reasoning=suppress_reasoning
            )

            tool_calls = assistant_msg.tool_calls
            if not tool_calls:
                text = assistant_msg.content or ""
                logger.info("llm_tool_response", model=self._config.llm_model, length=len(text))
                return text

            work_messages.append(assistant_msg.model_dump())

            for tc in tool_calls:
                tc_id = tc.id or ""
                fn_name = tc.function.name or ""
                try:
                    fn_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    fn_args = {}

                logger.info("tool_call", name=fn_name, tool_call_id=tc_id)
                result = await tool_handler(tc_id, fn_name, fn_args)
                work_messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})

        logger.warning("tool_max_rounds_exceeded", max_rounds=max_rounds)
        last_text = ""
        for msg_dict in reversed(work_messages):
            if isinstance(msg_dict, dict) and msg_dict.get("role") == "assistant":
                last_text = msg_dict.get("content") or ""
                break
        return last_text

    # -- internals -----------------------------------------------------------

    def _build_settings(self) -> LlmSettings:
        bsgateway_url = getattr(self._config, "bsgateway_url", "") or ""
        return LlmSettings(
            model=self._config.llm_model,
            bsgateway_url=bsgateway_url,
            route_default="bsgateway" if bsgateway_url else "direct",
        )

    def _build_metadata(self) -> RunAuditMetadata:
        # BSage is a single-user system; the gateway-side audit pipeline
        # accepts these placeholders without skipping audit.
        return RunAuditMetadata(tenant_id="bsage", run_id="local", agent_name="bsage")

    def _build_extra(self) -> dict[str, Any]:
        """Forward BSage's per-call api_key / api_base via LlmClient extra.

        bsvibe-llm doesn't model api_key on LlmSettings (it relies on env
        vars by convention). We pass it explicitly so BSage's existing
        config-driven flow keeps working with no env-var changes.
        """
        extra: dict[str, Any] = {}
        if self._config.llm_api_key:
            extra["api_key"] = self._config.llm_api_key
        if self._config.llm_api_base:
            extra["api_base"] = self._config.llm_api_base
        return extra

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        *,
        suppress_reasoning: bool = False,
    ) -> Message:
        """Run one completion through bsvibe-llm and return the assistant message."""
        client = LlmClient(settings=self._build_settings())
        # Direct mode unless an explicit BSGateway is configured. BSage's
        # default is local single-user, no gateway.
        direct = not (getattr(self._config, "bsgateway_url", "") or "")
        extra = self._build_extra()

        result = await client.complete(
            messages=messages,
            metadata=self._build_metadata(),
            tools=tools,
            direct=direct,
            extra=extra or None,
            suppress_reasoning=suppress_reasoning,
        )

        raw = result.raw
        if raw is None or not getattr(raw, "choices", None):
            raise RuntimeError("LLM returned empty choices")

        return raw.choices[0].message
