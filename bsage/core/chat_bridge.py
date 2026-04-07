"""ChatBridge — unified chat interface wrapping handle_chat + reply callback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.agent_loop import AgentLoop
    from bsage.core.prompt_registry import PromptRegistry
    from bsage.garden.ingest_compiler import IngestCompiler
    from bsage.garden.retriever import VaultRetriever
    from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)

# Async callback: (message) -> None
ReplyFn = Callable[[str], Awaitable[None]]


class ChatBridge:
    """Unified chat interface for all BSage channels.

    Wraps ``handle_chat`` with an optional *reply_fn* callback so every
    consumer (CLI, GUI, Telegram, Slack, …) uses the same vault-aware,
    tool-enabled chat pipeline.

    - Notify plugins: ``reply_fn=_make_reply_fn(source_name)``
    - CLI:            ``reply_fn=async msg: click.echo(…)``
    - GUI HTTP:       ``reply_fn=None`` (caller returns response directly)
    """

    def __init__(
        self,
        agent_loop: AgentLoop,
        garden_writer: GardenWriter,
        prompt_registry: PromptRegistry,
        retriever: VaultRetriever | None = None,
        reply_fn: ReplyFn | None = None,
        ingest_compiler: IngestCompiler | None = None,
    ) -> None:
        self._agent_loop = agent_loop
        self._garden_writer = garden_writer
        self._prompt_registry = prompt_registry
        self._retriever = retriever
        self._reply_fn = reply_fn
        self._ingest_compiler = ingest_compiler

    async def chat(
        self,
        message: str,
        history: list[dict[str, Any]] | None = None,
        context_paths: list[str] | None = None,
    ) -> str:
        """Run vault-aware chat and optionally deliver the reply via callback."""
        from bsage.gateway.chat import handle_chat

        reply = await handle_chat(
            message=message,
            history=history or [],
            agent_loop=self._agent_loop,
            garden_writer=self._garden_writer,
            prompt_registry=self._prompt_registry,
            context_paths=context_paths,
            retriever=self._retriever,
            ingest_compiler=self._ingest_compiler,
        )

        if reply and reply.strip() and self._reply_fn:
            try:
                await self._reply_fn(reply.strip())
            except Exception:
                logger.warning("reply_fn_failed", exc_info=True)

        return reply
