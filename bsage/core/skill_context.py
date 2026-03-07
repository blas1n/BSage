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


@runtime_checkable
class RetrieverInterface(Protocol):
    """Protocol for vault semantic search (VaultRetriever, mock, etc.)."""

    async def search(
        self,
        query: str,
        context_dirs: list[str] | None = None,
        max_chars: int = 50_000,
        top_k: int = 20,
    ) -> str: ...


@runtime_checkable
class SchedulerInterface(Protocol):
    """Protocol for dynamic cron job management."""

    async def add_cron(
        self,
        name: str,
        schedule: str,
        target: str,
        input_data: dict[str, Any] | None = None,
    ) -> None: ...

    async def remove_cron(self, name: str) -> None: ...

    async def list_jobs(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class EventEmitter(Protocol):
    """Protocol for emitting events to the EventBus."""

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None: ...


class RetrieverAdapter:
    """Adapts VaultRetriever to RetrieverInterface with default context_dirs."""

    def __init__(self, retriever: Any) -> None:
        self._retriever = retriever

    async def search(
        self,
        query: str,
        context_dirs: list[str] | None = None,
        max_chars: int = 50_000,
        top_k: int = 20,
    ) -> str:
        """Search vault notes semantically.

        Args:
            query: The search query text.
            context_dirs: Vault subdirectories to search.
                Defaults to seeds, garden/idea, garden/insight.
            max_chars: Maximum total characters to return.
            top_k: Maximum number of notes to retrieve.

        Returns:
            Concatenated note text with ``---`` separators.
        """
        dirs = context_dirs or ["seeds", "garden/idea", "garden/insight"]
        return await self._retriever.retrieve(
            query=query, context_dirs=dirs, max_chars=max_chars, top_k=top_k
        )


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
    retriever: RetrieverInterface | None = field(default=None)
    scheduler: SchedulerInterface | None = field(default=None)
    events: EventEmitter | None = field(default=None)
