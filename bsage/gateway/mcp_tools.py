"""Transport-agnostic MCP tool core.

Each function takes ``(state, params)`` and returns a plain dict so it can
be called from the REST router (``mcp.py`` / ``routes.py``), the stdio MCP
server, and the SSE MCP server with no FastAPI coupling.

These are the read tools plus ``create_note``. Source-specific imports
(ChatGPT/Claude/Obsidian) live in their own input plugins and are exposed
to MCP via ``bsage.mcp.plugin_bridge`` — not here.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from bsage.garden.markdown_utils import extract_frontmatter, extract_title
from bsage.garden.note import GardenNote

logger = structlog.get_logger(__name__)


# -- search_knowledge ---------------------------------------------------------


async def search_knowledge(state: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Semantic search across the vault.

    Tries vector store first, falls back to retriever.search.
    """
    query = params["query"]
    top_k = int(params.get("top_k", 10))

    results: list[dict[str, Any]] = []

    if state.vector_store is not None and state.embedder is not None and state.embedder.enabled:
        try:
            embedding = await state.embedder.embed(query)
            vector_results = await state.vector_store.search(embedding, top_k=top_k)
            for path, score in vector_results:
                try:
                    abs_path = state.vault.resolve_path(path)
                    content = await state.vault.read_note_content(abs_path)
                except (FileNotFoundError, OSError):
                    continue
                fm = extract_frontmatter(content)
                title = extract_title(content) or path.rsplit("/", 1)[-1].removesuffix(".md")
                tags = [str(t).lower() for t in fm.get("tags", []) or []]
                results.append(
                    {
                        "title": title,
                        "path": path,
                        "preview": _extract_body_preview(content),
                        "score": round(score, 4),
                        "tags": tags,
                    }
                )
            return {"results": results, "query": query}
        except (RuntimeError, OSError, ValueError):
            logger.warning("mcp_vector_search_fallback", exc_info=True)

    try:
        text = await state.retriever.search(query, top_k=top_k)
        results.append(
            {
                "title": "Search Results",
                "path": "",
                "preview": text[:500],
                "score": 1.0,
                "tags": [],
            }
        )
    except Exception:
        logger.warning("mcp_search_fallback_failed", exc_info=True)

    return {"results": results, "query": query}


# -- get_note -----------------------------------------------------------------


async def get_note(state: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Read a vault file by relative path."""
    path = params["path"]
    resolved = state.vault.resolve_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    content = await state.vault.read_note_content(resolved)
    return {"path": path, "content": content}


# -- get_graph_context --------------------------------------------------------


async def get_graph_context(state: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Knowledge graph traversal for a topic."""
    if state.graph_retriever is None:
        raise RuntimeError("Knowledge graph not available")

    topic = params["topic"]
    max_hops = int(params.get("max_hops", 2))
    top_k = int(params.get("top_k", 10))

    context = await state.graph_retriever.retrieve(topic, max_hops=max_hops, top_k=top_k)
    has_results = bool(context.strip())
    return {
        "topic": topic,
        "context": context if has_results else "No graph context found for this topic.",
        "has_results": has_results,
    }


# -- list_recent --------------------------------------------------------------


async def list_recent(state: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Vault catalog grouped by note type. Uses index_reader summaries."""
    summaries = await state.index_reader.get_all_summaries()
    by_type: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        key = getattr(s, "note_type", None) or "uncategorized"
        by_type.setdefault(key, []).append(
            {
                "title": s.title,
                "path": s.path,
                "tags": list(getattr(s, "tags", []) or []),
                "captured_at": getattr(s, "captured_at", None),
            }
        )
    return {"total": len(summaries), "categories": by_type}


# -- create_note --------------------------------------------------------------


async def create_note(
    state: Any,
    params: dict[str, Any],
    principal: Any | None = None,
) -> dict[str, Any]:
    """Create a garden note via GardenWriter.

    ``principal.tenant_id`` (when given) is stamped on the note for
    multi-tenant isolation. Without a principal the note is written
    without a tenant_id (stdio context).
    """
    title = params["title"]
    content = params.get("content", "")
    links = list(params.get("links", []) or [])
    if links:
        wikilinks = " ".join(f"[[{link}]]" for link in links)
        content = f"{content}\n\n{wikilinks}" if content else wikilinks

    tenant_id = getattr(principal, "tenant_id", None) if principal is not None else None

    note = GardenNote(
        title=title,
        content=content,
        note_type=params.get("note_type", "idea"),
        source=params.get("source", "mcp"),
        related=links,
        tags=list(params.get("tags", []) or []),
        extra_fields=dict(params.get("metadata", {}) or {}),
        tenant_id=tenant_id,
    )

    written_path = await state.garden_writer.write_garden(note)

    rel_path = str(written_path)
    with contextlib.suppress(ValueError, AttributeError):
        rel_path = str(written_path.relative_to(state.vault.root))

    return {
        "id": Path(rel_path).stem,
        "path": rel_path,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }


# -- helpers ------------------------------------------------------------------


def _extract_body_preview(content: str, max_len: int = 200) -> str:
    """Extract body preview from markdown, skipping frontmatter."""
    body = content
    if content.startswith("---\n"):
        try:
            end_idx = content.index("\n---\n", 4)
            body = content[end_idx + 5 :]
        except ValueError:
            pass
    return body.strip()[:max_len]
