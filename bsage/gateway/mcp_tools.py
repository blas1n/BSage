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
from typing import Any

import structlog

from bsage.garden.markdown_utils import extract_frontmatter, extract_title

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
    """Submit a note for ingestion.

    External MCP callers can't write garden notes directly — that
    boundary keeps classification + linking under BSage's control.
    Instead this tool writes a SEED and hands it to
    :class:`IngestCompiler`, which decides what garden notes to
    create / update / append against the existing vault.

    ``principal.tenant_id`` is stamped on the seed for tenant
    isolation. Without a principal (stdio context) the seed is
    written without a tenant_id.
    """
    title = params["title"]
    content = params.get("content", "")
    links = list(params.get("links", []) or [])
    if links:
        wikilinks = " ".join(f"[[{link}]]" for link in links)
        content = f"{content}\n\n{wikilinks}" if content else wikilinks

    tenant_id = getattr(principal, "tenant_id", None) if principal is not None else None
    source_label = params.get("source", "mcp")

    seed_data: dict[str, Any] = {
        "title": title,
        "content": content,
        "tags": list(params.get("tags", []) or []),
        "provenance": {
            "source": source_label,
            "submitted_via": "mcp",
            "submitted_at": datetime.now(tz=UTC).isoformat(),
        },
    }
    if tenant_id is not None:
        seed_data["tenant_id"] = tenant_id
    metadata = params.get("metadata") or {}
    if metadata:
        seed_data["metadata"] = dict(metadata)

    seed_path = await state.garden_writer.write_seed(f"mcp/{source_label}", seed_data)

    rel_seed_path = str(seed_path)
    with contextlib.suppress(ValueError, AttributeError):
        rel_seed_path = str(seed_path.relative_to(state.vault.root))

    notes_created = 0
    notes_updated = 0
    compiler_available = state.ingest_compiler is not None

    if compiler_available:
        try:
            result = await state.ingest_compiler.compile(
                seed_content=_format_mcp_compile_payload(seed_data, links),
                seed_source=f"mcp/{source_label}",
            )
            notes_created = result.notes_created
            notes_updated = result.notes_updated
        except Exception:
            logger.warning("mcp_create_note_compile_failed", exc_info=True)

    return {
        "seed_path": rel_seed_path,
        "submitted_at": seed_data["provenance"]["submitted_at"],
        "notes_created": notes_created,
        "notes_updated": notes_updated,
        "compiler_available": compiler_available,
    }


def _format_mcp_compile_payload(seed: dict[str, Any], links: list[str]) -> str:
    """Build the prompt payload IngestCompiler sees for an MCP submission."""
    parts = [f"# MCP submission: {seed['title']}", ""]
    if seed.get("tags"):
        parts.append(f"submitted_tags: {seed['tags']}")
    if links:
        parts.append(f"linked_titles: {links}")
    parts.extend(["", "---", "", seed["content"]])
    return "\n".join(parts)


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
