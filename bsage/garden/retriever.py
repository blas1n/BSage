"""VaultRetriever — index-based 2-step note retrieval with recency fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from bsage.garden.index_reader import NoteSummary

if TYPE_CHECKING:
    from bsage.garden.graph_retriever import GraphRetriever
    from bsage.garden.index_reader import IndexReader
    from bsage.garden.vault import Vault

logger = structlog.get_logger(__name__)


class VaultRetriever:
    """Index-based note retrieval.

    Step 1: Read index summaries (title + tags + metadata) for context dirs.
    Step 2: Return summaries as formatted context for LLM to process.

    Falls back to recency-based reading when index is not available.
    """

    def __init__(
        self,
        vault: Vault,
        index_reader: IndexReader | None = None,
        graph_retriever: GraphRetriever | None = None,
    ) -> None:
        self._vault = vault
        self._index_reader = index_reader
        self._graph_retriever = graph_retriever

    @property
    def index_available(self) -> bool:
        """True if an index reader is configured."""
        return self._index_reader is not None

    async def retrieve(
        self,
        query: str,
        context_dirs: list[str],
        max_chars: int = 50_000,
        top_k: int = 20,
    ) -> str:
        """Retrieve vault context as a formatted string.

        When index is available, returns index summaries so the LLM
        can identify relevant notes. Falls back to recency-based reading.

        Args:
            query: The search query (used for logging; LLM does the matching).
            context_dirs: Vault subdirectories to include.
            max_chars: Maximum total characters to return.
            top_k: Maximum number of notes per directory.

        Returns:
            Concatenated note text with ``---`` separators.
        """
        if self._index_reader is not None:
            try:
                return await self._index_retrieve(context_dirs, max_chars, top_k)
            except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError, RuntimeError):
                logger.warning("index_retrieve_failed_fallback", exc_info=True)

        return await self._fallback_retrieve(context_dirs, max_chars, top_k)

    async def search(
        self,
        query: str,
        context_dirs: list[str] | None = None,
        top_k: int = 10,
    ) -> str:
        """Search vault using index — returns index listing for LLM to interpret.

        Used by the search-vault tool. Returns a formatted index listing
        that the LLM can use to identify which notes are relevant.

        Args:
            query: Search query (included in output for LLM context).
            context_dirs: Optional filter by directories.
            top_k: Max results.

        Returns:
            Formatted search results string.
        """
        if self._index_reader is None:
            dirs = context_dirs or ["seeds", "garden/idea", "garden/insight"]
            return await self._fallback_retrieve(dirs, max_chars=20_000, max_notes_per_dir=top_k)

        if context_dirs:
            summaries: list[NoteSummary] = []
            for d in context_dirs:
                summaries.extend(await self._index_reader.get_summaries(d))
        else:
            summaries = await self._index_reader.get_all_summaries()

        summaries = summaries[:top_k]

        if not summaries:
            return "No notes found."

        lines = [f"Found {len(summaries)} notes (query: {query}):"]
        lines.append("")
        for s in summaries:
            tags_str = ", ".join(f"#{t}" for t in s.tags) if s.tags else ""
            related_str = ", ".join(s.related[:3]) if s.related else ""
            lines.append(f"- **{s.title}** ({s.path})")
            if tags_str:
                lines.append(f"  Tags: {tags_str}")
            if related_str:
                lines.append(f"  Related: {related_str}")
            if s.captured_at:
                lines.append(f"  Date: {s.captured_at}")

        index_result = "\n".join(lines)

        # Append graph context if available
        if self._graph_retriever is not None:
            try:
                graph_context = await self._graph_retriever.retrieve(query, top_k=top_k)
                if graph_context:
                    return index_result + "\n\n" + graph_context
            except (FileNotFoundError, OSError, ValueError):
                logger.debug("graph_search_failed", exc_info=True)

        return index_result

    async def _index_retrieve(
        self,
        context_dirs: list[str],
        max_chars: int,
        top_k: int,
    ) -> str:
        """Retrieve using index: return summaries + recent full notes."""
        if self._index_reader is None:
            return await self._fallback_retrieve(context_dirs, max_chars, top_k)

        all_summaries: list[NoteSummary] = []
        for d in context_dirs:
            all_summaries.extend(await self._index_reader.get_summaries(d))

        if not all_summaries:
            logger.debug("index_no_summaries_fallback", dirs=context_dirs)
            return await self._fallback_retrieve(context_dirs, max_chars, top_k)

        # Sort by date (most recent first)
        all_summaries.sort(key=lambda s: s.captured_at or "0000-00-00", reverse=True)
        all_summaries = all_summaries[:top_k]

        # Build context: index listing + recent note contents
        parts: list[str] = []
        total = 0

        # Part 1: Index summary table
        index_header = "## Note Index\n"
        index_lines = [index_header]
        index_lines.append("| Title | Tags | Date |")
        index_lines.append("|-------|------|------|")
        for s in all_summaries:
            tags_str = ", ".join(f"#{t}" for t in s.tags) if s.tags else ""
            index_lines.append(f"| [[{s.title}]] | {tags_str} | {s.captured_at} |")
        index_text = "\n".join(index_lines)
        parts.append(index_text)
        total += len(index_text)

        # Part 2: Full content of most recent notes (fit within max_chars)
        recent = all_summaries[:5]  # Read up to 5 most recent full notes
        for s in recent:
            if total >= max_chars:
                break
            try:
                path = self._vault.resolve_path(s.path)
                content = await self._vault.read_note_content(path)
                remaining = max_chars - total
                parts.append(content[:remaining])
                total += len(parts[-1])
            except (FileNotFoundError, OSError, UnicodeDecodeError):
                logger.debug("index_read_note_failed", path=s.path)

        logger.info(
            "index_retrieve",
            count=len(all_summaries),
            total_chars=total,
        )
        return "\n---\n".join(parts)

    async def _fallback_retrieve(
        self,
        context_dirs: list[str],
        max_chars: int,
        max_notes_per_dir: int,
    ) -> str:
        """Recency-based retrieval fallback."""
        parts: list[str] = []
        total = 0

        for subdir in context_dirs:
            if total >= max_chars:
                break
            try:
                note_paths = await self._vault.read_notes(subdir)
            except (FileNotFoundError, OSError):
                continue
            for path in reversed(note_paths[-max_notes_per_dir:]):
                if total >= max_chars:
                    break
                try:
                    text = await self._vault.read_note_content(path)
                    remaining = max_chars - total
                    parts.append(text[:remaining])
                    total += len(parts[-1])
                except (FileNotFoundError, OSError, UnicodeDecodeError):
                    pass

        return "\n---\n".join(parts)

    async def reindex_all(self) -> int:
        """Full reindex of vault notes via FileIndexReader."""
        if self._index_reader is None:
            raise RuntimeError("Index reader not configured")
        await self._index_reader.rebuild_all()
        summaries = await self._index_reader.get_all_summaries()
        logger.info("reindex_complete", total=len(summaries))
        return len(summaries)
