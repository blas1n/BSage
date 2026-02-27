"""VaultRetriever — semantic search over vault notes with graceful fallback."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import yaml

from bsage.garden.vector_store import NoteEmbedding

if TYPE_CHECKING:
    from bsage.garden.embeddings import EmbeddingClient
    from bsage.garden.vault import Vault
    from bsage.garden.vector_store import VectorStore

logger = structlog.get_logger(__name__)

_MAX_EMBEDDING_TEXT = 8_000


def _extract_metadata(text: str) -> dict:
    """Extract frontmatter metadata from a note's text."""
    if not text.startswith("---\n"):
        return {}
    try:
        end_idx = text.index("\n---\n", 4)
        fm = yaml.safe_load(text[4:end_idx])
        return fm if isinstance(fm, dict) else {}
    except (ValueError, yaml.YAMLError):
        return {}


def _strip_frontmatter(text: str) -> str:
    """Return text content without YAML frontmatter."""
    if not text.startswith("---\n"):
        return text
    try:
        end_idx = text.index("\n---\n", 4)
        return text[end_idx + 5 :]
    except ValueError:
        return text


def _content_hash(text: str) -> str:
    """SHA-256 hex digest of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VaultRetriever:
    """Semantic search over vault notes.

    When embeddings are available, uses cosine similarity to find relevant notes.
    Falls back to recency-based approach when RAG is not configured or fails.
    """

    def __init__(
        self,
        vault: Vault,
        vector_store: VectorStore | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._vault = vault
        self._vector_store = vector_store
        self._embedding_client = embedding_client

    @property
    def rag_available(self) -> bool:
        """True if both vector store and embedding client are configured."""
        return self._vector_store is not None and self._embedding_client is not None

    async def retrieve(
        self,
        query: str,
        context_dirs: list[str],
        max_chars: int = 50_000,
        top_k: int = 20,
    ) -> str:
        """Retrieve relevant vault notes as a concatenated context string.

        If RAG is available, embeds the query and searches semantically.
        Otherwise, falls back to recency-based reading.

        Args:
            query: The search query (user message or skill description).
            context_dirs: Vault subdirectories to search within.
            max_chars: Maximum total characters to return.
            top_k: Maximum number of notes to retrieve.

        Returns:
            Concatenated note text with ``---`` separators.
        """
        if self.rag_available:
            try:
                return await self._semantic_retrieve(query, context_dirs, max_chars, top_k)
            except Exception:
                logger.warning("rag_retrieve_failed_fallback", exc_info=True)

        return await self._fallback_retrieve(context_dirs, max_chars, top_k)

    async def _semantic_retrieve(
        self,
        query: str,
        context_dirs: list[str],
        max_chars: int,
        top_k: int,
    ) -> str:
        """Embed query and search vector store."""
        assert self._embedding_client is not None
        assert self._vector_store is not None

        query_vec = await self._embedding_client.embed_one(query[:_MAX_EMBEDDING_TEXT])
        results = await self._vector_store.search(query_vec, top_k=top_k * 2)

        # Filter to notes within the requested context_dirs
        dir_prefixes = tuple(d.rstrip("/") + "/" for d in context_dirs)
        filtered = [r for r in results if any(r.note_path.startswith(p) for p in dir_prefixes)]
        filtered = filtered[:top_k]

        if not filtered:
            logger.debug("rag_no_results_fallback", dirs=context_dirs)
            return await self._fallback_retrieve(context_dirs, max_chars, top_k)

        parts: list[str] = []
        total = 0
        for result in filtered:
            if total >= max_chars:
                break
            try:
                path = self._vault.resolve_path(result.note_path)
                content = await self._vault.read_note_content(path)
                remaining = max_chars - total
                parts.append(content[:remaining])
                total += len(parts[-1])
            except Exception:
                logger.debug("rag_read_note_failed", path=result.note_path)

        logger.info(
            "rag_retrieve",
            count=len(parts),
            total_chars=total,
            query_preview=query[:50],
        )
        return "\n---\n".join(parts)

    async def _fallback_retrieve(
        self,
        context_dirs: list[str],
        max_chars: int,
        max_notes_per_dir: int,
    ) -> str:
        """Original recency-based retrieval (current behavior)."""
        parts: list[str] = []
        total = 0

        for subdir in context_dirs:
            if total >= max_chars:
                break
            try:
                note_paths = await self._vault.read_notes(subdir)
            except Exception:
                continue
            for path in reversed(note_paths[-max_notes_per_dir:]):
                if total >= max_chars:
                    break
                try:
                    text = await self._vault.read_note_content(path)
                    remaining = max_chars - total
                    parts.append(text[:remaining])
                    total += len(parts[-1])
                except Exception:
                    pass

        return "\n---\n".join(parts)

    async def index_note(self, note_path: str, content: str) -> None:
        """Index a single note into the vector store.

        Skips indexing if the note hasn't changed (same content_hash).

        Args:
            note_path: Relative path within the vault.
            content: Full text content of the note.
        """
        if not self.rag_available:
            return

        assert self._vector_store is not None
        assert self._embedding_client is not None

        c_hash = _content_hash(content)
        existing_hash = await self._vector_store.get_content_hash(note_path)
        if existing_hash == c_hash:
            logger.debug("index_skip_unchanged", note_path=note_path)
            return

        metadata = _extract_metadata(content)
        title = metadata.get("title", "")
        note_type = metadata.get("type", "")
        source = metadata.get("source", "")

        body = _strip_frontmatter(content)
        embed_text = f"{title}\n{body}".strip()[:_MAX_EMBEDDING_TEXT]

        try:
            vector = await self._embedding_client.embed_one(embed_text)
        except Exception:
            logger.warning("index_embedding_failed", note_path=note_path, exc_info=True)
            return

        record = NoteEmbedding(
            note_path=note_path,
            content_hash=c_hash,
            title=title,
            note_type=note_type,
            source=source,
            embedding=vector,
            indexed_at=datetime.now(tz=UTC).isoformat(),
        )
        await self._vector_store.upsert(record)
        logger.info("note_indexed", note_path=note_path, note_type=note_type)

    async def reindex_all(
        self,
        dirs: list[str] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Full reindex of vault notes.

        Args:
            dirs: Subdirectories to index. Defaults to ``["seeds", "garden"]``.
            on_progress: Optional callback ``(indexed, total)`` for progress.

        Returns:
            Number of notes indexed.
        """
        if not self.rag_available:
            raise RuntimeError("RAG not available: embedding model or vector store not configured")

        target_dirs = dirs or ["seeds", "garden"]
        all_paths = await self._collect_note_paths(target_dirs)

        total = len(all_paths)
        indexed = 0
        for i, (rel_path, abs_path) in enumerate(all_paths):
            try:
                content = await self._vault.read_note_content(abs_path)
                await self.index_note(rel_path, content)
                indexed += 1
            except Exception:
                logger.warning("reindex_note_failed", path=rel_path, exc_info=True)
            if on_progress:
                on_progress(i + 1, total)

        # Clean up stale entries
        assert self._vector_store is not None
        indexed_paths = await self._vector_store.all_paths()
        current_paths = {rel for rel, _ in all_paths}
        stale = indexed_paths - current_paths
        for stale_path in stale:
            await self._vector_store.delete(stale_path)

        logger.info(
            "reindex_complete",
            indexed=indexed,
            total=total,
            stale_removed=len(stale),
        )
        return indexed

    async def _collect_note_paths(self, target_dirs: list[str]) -> list[tuple[str, Path]]:
        """Collect all .md note paths from target directories (including subdirs)."""
        all_paths: list[tuple[str, Path]] = []
        for subdir in target_dirs:
            try:
                note_paths = await self._vault.read_notes(subdir)
                for p in note_paths:
                    rel = str(p.relative_to(self._vault.root))
                    all_paths.append((rel, p))
            except Exception:
                # Try subdirectories (e.g. seeds/chat, garden/idea)
                base = self._vault.resolve_path(subdir)
                if base.is_dir():
                    for child in sorted(base.iterdir()):
                        if child.is_dir():
                            child_sub = f"{subdir}/{child.name}"
                            try:
                                paths = await self._vault.read_notes(child_sub)
                                for p in paths:
                                    rel = str(p.relative_to(self._vault.root))
                                    all_paths.append((rel, p))
                            except Exception:
                                pass
        return all_paths
