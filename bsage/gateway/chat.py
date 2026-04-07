"""Chat service — vault-aware conversational AI for BSage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.agent_loop import AgentLoop
    from bsage.core.prompt_registry import PromptRegistry
    from bsage.garden.ingest_compiler import IngestCompiler
    from bsage.garden.retriever import VaultRetriever
    from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)

DEFAULT_CONTEXT_PATHS: list[str] = ["garden/idea", "garden/insight"]
_MAX_CONTEXT_CHARS = 16_000


async def gather_vault_context(
    garden_writer: GardenWriter,
    context_paths: list[str],
    max_chars: int = _MAX_CONTEXT_CHARS,
    retriever: VaultRetriever | None = None,
    query: str = "",
) -> str:
    """Read relevant vault notes and concatenate them up to *max_chars*.

    Uses index-based retrieval when *retriever* is available and a
    *query* is provided.  Falls back to recency-based reading otherwise.
    """
    if retriever and query:
        try:
            return await retriever.retrieve(
                query=query,
                context_dirs=context_paths,
                max_chars=max_chars,
            )
        except Exception:
            logger.warning("chat_index_fallback", exc_info=True)

    # Original recency-based fallback
    segments: list[str] = []
    total = 0

    for subdir in context_paths:
        try:
            note_paths = await garden_writer.read_notes(subdir)
        except Exception:
            logger.debug("vault_context_skip_dir", subdir=subdir)
            continue

        for path in reversed(note_paths):
            if total >= max_chars:
                break
            try:
                content = await garden_writer.read_note_content(path)
            except Exception:
                continue
            segment = f"## {path.name}\n{content}\n"
            segments.append(segment)
            total += len(segment)

        if total >= max_chars:
            break

    result = "\n".join(segments)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n...(truncated)"
    return result


def build_system_prompt(prompt_registry: PromptRegistry, vault_context: str) -> str:
    """Build the system prompt with vault context injected."""
    if vault_context.strip():
        section = f"Your knowledge base contains these notes:\n\n{vault_context}"
    else:
        section = "The knowledge base is currently empty. Help the user get started."

    identity = prompt_registry.get("system")
    chat_instructions = prompt_registry.render("chat", context_section=section)
    return f"{identity}\n\n{chat_instructions}"


async def handle_chat(
    message: str,
    history: list[dict[str, Any]],
    agent_loop: AgentLoop,
    garden_writer: GardenWriter,
    prompt_registry: PromptRegistry,
    context_paths: list[str] | None = None,
    retriever: VaultRetriever | None = None,
    ingest_compiler: IngestCompiler | None = None,
) -> str:
    """Process a chat request via AgentLoop with skill tool use."""
    paths = context_paths or DEFAULT_CONTEXT_PATHS
    vault_context = await gather_vault_context(
        garden_writer, paths, retriever=retriever, query=message
    )
    system = build_system_prompt(prompt_registry, vault_context)

    messages = [*history, {"role": "user", "content": message}]
    response = await agent_loop.chat(system=system, messages=messages)

    # Brief one-line summary for the daily action log
    first_line = response.split("\n", 1)[0].strip()
    summary = f"User: {message[:80]} | Assistant: {first_line[:120]}"
    await garden_writer.write_action("chat", summary)

    # Full transcript as a seed for downstream ProcessSkills
    await garden_writer.write_seed("chat", {"user": message, "assistant": response})

    # Promote valuable Q&A to garden notes (Karpathy Wiki pattern)
    if ingest_compiler:
        await ingest_compiler.compile(
            seed_content=f"Q: {message}\nA: {response}",
            seed_source="chat",
        )

    return response
