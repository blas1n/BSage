"""SkillContext — the context object injected into every Skill execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from bsage.garden.writer import GardenWriter

if TYPE_CHECKING:
    from bsage.garden.ingest_compiler import BatchItem, CompileResult

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
class GraphInterface(Protocol):
    """Protocol for graph queries (subset exposed to plugins)."""

    async def count_relationships_for_entity(self, entity_name: str) -> int: ...

    async def count_distinct_sources(self, entity_name: str) -> int: ...

    async def get_entity_updated_at(self, entity_name: str) -> str | None: ...


@runtime_checkable
class EventEmitter(Protocol):
    """Protocol for emitting events to the EventBus."""

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class IngestCompilerInterface(Protocol):
    """Protocol for the ingest-time compiler exposed to plugins/MCP.

    The only sanctioned route by which an external surface can produce
    garden notes — the compiler classifies seeds against existing notes
    (via LLM) and decides what to create / update / append, so plugins
    never have to pre-classify themselves.

    Always batched: even a single seed goes through ``compile_batch`` so
    the prompt + chunking + LLM-cost behaviour is uniform across every
    caller.
    """

    async def compile_batch(self, items: list[BatchItem], seed_source: str) -> CompileResult: ...


class RestrictedPluginGarden:
    """Read + seed-only wrapper around :class:`GardenWriter`.

    External surfaces (plugins, MCP) get this wrapper instead of the raw
    writer so they cannot edit garden notes directly. They can only:

    * write seeds (raw collected data)
    * read existing notes (for context)
    * resolve a per-plugin state path (cursor/offset persistence)

    Anything that would mutate ``garden/`` (write_garden, update_note,
    append_to_note, delete_note, mark_*) goes through ``IngestCompiler``
    instead, which is the single sanctioned write surface.
    """

    __slots__ = ("_writer",)

    # Methods that produce or mutate garden notes — blocked here so external
    # callers route through IngestCompiler instead.
    _BLOCKED: tuple[str, ...] = (
        "write_garden",
        "update_note",
        "append_to_note",
        "delete_note",
        "mark_evergreen",
        "mark_archived",
        "promote_status",
        "handle_write_note",
        "handle_update_note",
        "handle_append_note",
        "handle_delete_note",
    )

    def __init__(self, writer: GardenWriter) -> None:
        self._writer = writer

    # -- allowed pass-through methods --------------------------------------

    async def write_seed(self, source: str, data: dict[str, Any]) -> Path:
        return await self._writer.write_seed(source, data)

    async def write_input_log(self, source: str, raw_summary: str) -> Path:
        return await self._writer.write_input_log(source, raw_summary)

    async def write_action(self, name: str, summary: str) -> Path:
        return await self._writer.write_action(name, summary)

    async def read_notes(self, subdir: str) -> list[Path]:
        return await self._writer.read_notes(subdir)

    async def read_note_content(self, path: Path) -> str:
        return await self._writer.read_note_content(path)

    def resolve_plugin_state_path(self, plugin_name: str, subpath: str = "_state.json") -> Path:
        return self._writer.resolve_plugin_state_path(plugin_name, subpath)

    # -- explicit blocks ---------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if name in self._BLOCKED:
            raise PermissionError(
                f"'{name}' is not available to plugins/MCP — submit a seed "
                "via write_seed() and let IngestCompiler classify it."
            )
        raise AttributeError(name)


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

    garden: GardenWriter | RestrictedPluginGarden
    llm: LLMClient
    config: dict[str, Any]
    logger: structlog.typing.FilteringBoundLogger | Any
    credentials: dict[str, Any] = field(default_factory=dict)
    input_data: dict[str, Any] | None = field(default=None)
    chat: ChatInterface | None = field(default=None)
    retriever: RetrieverInterface | None = field(default=None)
    scheduler: SchedulerInterface | None = field(default=None)
    events: EventEmitter | None = field(default=None)
    graph: GraphInterface | None = field(default=None)
    ingest_compiler: IngestCompilerInterface | None = field(default=None)
