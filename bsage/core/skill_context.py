"""SkillContext — the context object injected into every Skill execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog

from bsage.garden.writer import GardenWriter

# Type alias for tool handlers: (tool_call_id, function_name, arguments) -> result JSON
ToolHandler = Callable[[str, str, dict[str, Any]], Awaitable[str]]


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM chat clients (litellm, mock, etc.)."""

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_handler: ToolHandler | None = None,
        max_rounds: int = 10,
    ) -> str: ...


@runtime_checkable
class ChatInterface(Protocol):
    """Protocol for vault-aware chat (ChatBridge, mock, etc.)."""

    async def chat(
        self,
        message: str,
        history: list[dict] | None = None,
        context_paths: list[str] | None = None,
    ) -> str: ...


@dataclass
class SkillContext:
    """Context object injected into every skill execution.

    Skills access the outside world exclusively through this object:
    - credentials — auto-injected dict of resolved credentials for this skill
    - garden.write_seed / write_garden / write_action — vault I/O
    - llm.chat — LLM API calls
    - chat.chat — vault-aware conversational chat (via ChatBridge)
    - config — skill-specific configuration
    - logger — structured logger
    """

    garden: GardenWriter
    llm: LLMClient
    config: dict[str, Any]
    logger: structlog.typing.FilteringBoundLogger | Any
    credentials: dict[str, Any] = field(default_factory=dict)
    input_data: dict[str, Any] | None = field(default=None)
    chat: ChatInterface | None = field(default=None)
