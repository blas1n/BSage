"""VaultRetriever — hybrid search over vault notes with graceful fallback."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import yaml

from bsage.core.config import get_settings
from bsage.core.patterns import RELATED_RE, WIKILINK_RE
from bsage.garden.vector_store import NoteEmbedding

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.garden.embeddings import EmbeddingClient
    from bsage.garden.vault import Vault
    from bsage.garden.vector_store import VectorStore
    from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)
settings = get_settings()


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
    """SHA-256 hex digest of text content, ignoring the ``related`` field.

    Stripping ``related`` from frontmatter before hashing prevents
    re-indexing loops when auto-links are written back to the note file.
    """
    stable = _strip_related_field(text)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _strip_related_field(text: str) -> str:
    """Remove the ``related`` key from YAML frontmatter for stable hashing.

    Uses regex surgery on the raw frontmatter string to avoid YAML round-trip
    which would alter key ordering, quoting style, and strip comments.
    """
    if not text.startswith("---\n"):
        return text
    try:
        end_idx = text.index("\n---\n", 4)
    except ValueError:
        return text
    fm_str = text[4:end_idx]
    cleaned = RELATED_RE.sub("", fm_str)
    if cleaned == fm_str:
        return text  # No related field found
    # rstrip ensures we don't produce a double newline before --- when the
    # related field was the last key in frontmatter (and its preceding key's
    # \n stays after removal).
    return f"---\n{cleaned.rstrip(chr(10))}\n---\n{text[end_idx + 5 :]}"


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
        semantic_weight: float = 0.6,
        fts_weight: float = 0.25,
        link_weight: float = 0.15,
        link_expansion_k: int = 5,
        event_bus: EventBus | None = None,
        garden_writer: GardenWriter | None = None,
    ) -> None:
        self._vault = vault
        self._vector_store = vector_store
        self._embedding_client = embedding_client
        self._semantic_weight = semantic_weight
        self._fts_weight = fts_weight
        self._link_weight = link_weight
        self._link_expansion_k = link_expansion_k
        self._event_bus = event_bus
        self._garden_writer = garden_writer
        self._file_write_lock = asyncio.Lock()

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
                if self._vector_store is None or self._embedding_client is None:
                    return await self._fallback_retrieve(context_dirs, max_chars, top_k)
                if self._vector_store.fts_available:
                    return await self._hybrid_retrieve(query, context_dirs, max_chars, top_k)
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
        if self._embedding_client is None or self._vector_store is None:
            return await self._fallback_retrieve(context_dirs, max_chars, top_k)

        query_vec = await self._embedding_client.embed_one(query[:settings.max_embedding_text])
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

    async def _hybrid_retrieve(
        self,
        query: str,
        context_dirs: list[str],
        max_chars: int,
        top_k: int,
    ) -> str:
        """Combine semantic + FTS5 + link expansion via Reciprocal Rank Fusion."""
        if self._embedding_client is None or self._vector_store is None:
            return await self._fallback_retrieve(context_dirs, max_chars, top_k)

        # 1) Embed query, then run semantic + FTS in parallel
        query_vec = await self._embedding_client.embed_one(query[:settings.max_embedding_text])
        semantic_results, fts_results = await asyncio.gather(
            self._vector_store.search(query_vec, top_k=top_k * 2),
            self._vector_store.fts_search(query, top_k=top_k * 2),
        )

        # 2) Filter by context_dirs
        dir_prefixes = tuple(d.rstrip("/") + "/" for d in context_dirs)
        sem_filtered = [
            r for r in semantic_results if any(r.note_path.startswith(p) for p in dir_prefixes)
        ]
        fts_filtered = [
            r for r in fts_results if any(r.note_path.startswith(p) for p in dir_prefixes)
        ]

        # 3) RRF scoring: semantic + FTS
        k = 60  # standard RRF constant
        scores: dict[str, float] = {}
        for rank, r in enumerate(sem_filtered):
            scores[r.note_path] = scores.get(r.note_path, 0) + self._semantic_weight / (k + rank)
        for rank, r in enumerate(fts_filtered):
            scores[r.note_path] = scores.get(r.note_path, 0) + self._fts_weight / (k + rank)

        # 4) Link expansion — boost notes linked from top results (single batch query)
        if not fts_results:
            logger.debug("hybrid_fts_unavailable_or_empty", using="semantic_only")
        top_initial = sorted(scores, key=lambda p: scores[p], reverse=True)[
            : self._link_expansion_k
        ]
        linked_batch = await self._vector_store.get_linked_paths_batch(top_initial)
        # Each linked note is boosted at most once to prevent over-representation
        # when it appears in multiple top results' link sets.
        boosted: set[str] = set()
        for path in top_initial:
            for lp in linked_batch.get(path, set()):
                if lp not in boosted and any(lp.startswith(p) for p in dir_prefixes):
                    scores[lp] = scores.get(lp, 0) + self._link_weight / k
                    boosted.add(lp)

        ranked_paths = sorted(scores, key=lambda p: scores[p], reverse=True)[:top_k]

        if not ranked_paths:
            logger.debug("hybrid_no_results_fallback", dirs=context_dirs)
            return await self._fallback_retrieve(context_dirs, max_chars, top_k)

        # 5) Read content
        parts: list[str] = []
        total = 0
        for note_path in ranked_paths:
            if total >= max_chars:
                break
            try:
                path = self._vault.resolve_path(note_path)
                content = await self._vault.read_note_content(path)
                remaining = max_chars - total
                parts.append(content[:remaining])
                total += len(parts[-1])
            except Exception:
                logger.debug("hybrid_read_note_failed", path=note_path)

        logger.info(
            "hybrid_retrieve",
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

    async def index_note(
        self, note_path: str, content: str, *, skip_auto_links: bool = False
    ) -> list[float] | None:
        """Index a single note into the vector store.

        Skips indexing if the note hasn't changed (same content_hash).

        Args:
            note_path: Relative path within the vault.
            content: Full text content of the note.
            skip_auto_links: If True, skip auto-similarity search and
                frontmatter related update.  Used by ``reindex_all`` which
                runs a separate auto-link pass after all notes are indexed.

        Returns:
            The embedding vector if indexing occurred, None otherwise.
        """
        if not self.rag_available:
            return None

        if self._vector_store is None or self._embedding_client is None:
            return None

        c_hash = _content_hash(content)
        existing_hash = await self._vector_store.get_content_hash(note_path)
        if existing_hash == c_hash:
            logger.debug("index_skip_unchanged", note_path=note_path)
            return None

        metadata = _extract_metadata(content)
        title = metadata.get("title", "")
        note_type = metadata.get("type", "")
        source = metadata.get("source", "")

        body = _strip_frontmatter(content)
        embed_text = f"{title}\n{body}".strip()[:settings.max_embedding_text]

        try:
            vector = await self._embedding_client.embed_one(embed_text)
        except Exception:
            logger.warning("index_embedding_failed", note_path=note_path, exc_info=True)
            return None

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

        # FTS indexing — append wiki-link targets to body for keyword discoverability
        if self._vector_store.fts_available:
            link_targets = WIKILINK_RE.findall(body)
            fts_body = body + "\n" + " ".join(link_targets) if link_targets else body
            await self._vector_store.upsert_fts(note_path, title, fts_body)

        # Explicit links — extract [[wiki-links]] from full content
        all_link_targets = WIKILINK_RE.findall(content)
        if all_link_targets:
            resolved = await self._resolve_link_targets(all_link_targets)
            if resolved:
                await self._vector_store.upsert_links(note_path, resolved, link_type="explicit")

        if not skip_auto_links:
            await self._run_auto_links(note_path, vector)

        logger.info("note_indexed", note_path=note_path, note_type=note_type)
        return vector

    async def remove_note(self, note_path: str) -> None:
        """Remove a note from the vector store index.

        No-op if RAG is not available.

        Args:
            note_path: Relative path within the vault.
        """
        if not self.rag_available:
            return
        if self._vector_store is None:
            return
        await self._vector_store.delete(note_path)
        if self._vector_store.fts_available:
            await self._vector_store.delete_fts(note_path)
        await self._vector_store.delete_links(note_path)
        logger.info("note_removed_from_index", note_path=note_path)

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
        indexed_vectors: dict[str, list[float]] = {}

        # Phase 1: Index all notes (skip auto-links until all are indexed)
        for i, (rel_path, abs_path) in enumerate(all_paths):
            try:
                content = await self._vault.read_note_content(abs_path)
                vector = await self.index_note(rel_path, content, skip_auto_links=True)
                indexed += 1
                if vector is not None:
                    indexed_vectors[rel_path] = vector
            except Exception:
                logger.warning("reindex_note_failed", path=rel_path, exc_info=True)
            if on_progress:
                on_progress(i + 1, total)

        # Phase 2: Auto-link pass (all notes now indexed → accurate similarity)
        for note_path, vector in indexed_vectors.items():
            try:
                await self._run_auto_links(note_path, vector)
            except Exception:
                logger.warning("auto_link_failed", path=note_path, exc_info=True)

        # Clean up stale entries
        if self._vector_store is None:
            return indexed
        indexed_paths = await self._vector_store.all_paths()
        current_paths = {rel for rel, _ in all_paths}
        stale = indexed_paths - current_paths
        for stale_path in stale:
            await self._vector_store.delete(stale_path)
            if self._vector_store.fts_available:
                await self._vector_store.delete_fts(stale_path)
            await self._vector_store.delete_links(stale_path)

        logger.info(
            "reindex_complete",
            indexed=indexed,
            total=total,
            stale_removed=len(stale),
        )
        return indexed

    async def _run_auto_links(self, note_path: str, vector: list[float] | None = None) -> None:
        """Compute auto-similarity links and update note frontmatter.

        If *vector* is not provided, retrieves the stored embedding from the
        vector store.  This allows ``reindex_all`` to call this method after
        all notes are indexed without re-embedding.
        """
        if self._vector_store is None:
            return

        if vector is None:
            vector = await self._vector_store.get_embedding(note_path)
            if vector is None:
                return

        # Auto links — top-3 similar notes by vector similarity
        auto_similar = await self._vector_store.search(vector, top_k=4)
        auto_paths = [r.note_path for r in auto_similar if r.note_path != note_path][:3]
        if auto_paths:
            await self._vector_store.upsert_links(note_path, auto_paths, link_type="auto")

        # Write auto-discovered links to the note's frontmatter ``related`` field
        # so they appear in Obsidian's graph view and backlinks panel.
        all_linked = await self._vector_store.get_linked_paths(note_path)
        if all_linked:
            await self._update_note_related(note_path, all_linked)

    async def _resolve_link_targets(self, targets: list[str]) -> list[str]:
        """Resolve wiki-link targets to vault-relative paths.

        Tries exact path, then path + .md. Skips unresolvable targets.
        All filesystem checks are batched into a single thread call.
        """
        unique_targets = list(dict.fromkeys(targets))  # dedupe, preserve order

        def _resolve_sync() -> list[str]:
            resolved: list[str] = []
            for target in unique_targets:
                for suffix in ("", ".md"):
                    try:
                        p = self._vault.resolve_path(target + suffix)
                        if p.exists():
                            resolved.append(str(p.relative_to(self._vault.root)))
                            break
                    except (ValueError, OSError):
                        pass
            return resolved

        return await asyncio.to_thread(_resolve_sync)

    async def _update_note_related(self, note_path: str, linked_paths: set[str]) -> None:
        """Write auto-discovered links into the note's frontmatter ``related`` field.

        Converts vault-relative paths to ``[[wiki-link]]`` format and merges
        with any existing ``related`` entries.  Delegates to GardenWriter when
        available; otherwise writes directly to file.  Emits ``NOTE_UPDATED``
        so output plugins can sync.  IndexSubscriber will skip re-indexing
        because ``_content_hash`` excludes the ``related`` field.
        """
        if self._garden_writer is not None:
            await self._garden_writer.update_frontmatter_related(note_path, linked_paths)
            return

        async with self._file_write_lock:
            try:
                abs_path = self._vault.resolve_path(note_path)
                if not abs_path.resolve().is_relative_to(self._vault.root.resolve()):
                    logger.warning("path_traversal_blocked", note_path=note_path)
                    return
                if not abs_path.exists():
                    return
                content = await self._vault.read_note_content(abs_path)
            except Exception:
                return

            if not content.startswith("---\n"):
                return  # No frontmatter — skip
            try:
                end_idx = content.index("\n---\n", 4)
            except ValueError:
                return

            fm_str = content[4:end_idx]
            body = content[end_idx + 5 :]

            # Read existing related entries (read-only via YAML parse)
            metadata = _extract_metadata(content)
            if not metadata:
                return

            # Build wiki-link set from linked paths (stem only, Obsidian style)
            new_links: set[str] = set()
            for lp in linked_paths:
                stem = Path(lp).stem  # garden/idea/my-note.md → my-note
                new_links.add(f"[[{stem}]]")

            # Merge with existing related entries
            existing_related = metadata.get("related", [])
            existing_set = set(existing_related) if isinstance(existing_related, list) else set()

            merged = sorted(existing_set | new_links)
            if merged == sorted(existing_related if isinstance(existing_related, list) else []):
                return  # No change needed

            # Build the new related block as raw YAML text
            related_lines = "related:\n" + "".join(f"- '{link}'\n" for link in merged)

            # Replace or append the related block in raw frontmatter
            if RELATED_RE.search(fm_str):
                updated_fm = RELATED_RE.sub(related_lines, fm_str)
            else:
                # Append to end of frontmatter (ensure trailing newline)
                sep = "" if fm_str.endswith("\n") else "\n"
                updated_fm = fm_str + sep + related_lines

            new_content = f"---\n{updated_fm}---\n{body}"

            await asyncio.to_thread(abs_path.write_text, new_content, encoding="utf-8")
            logger.debug("note_related_updated", note_path=note_path, links=len(merged))

            if self._event_bus:
                from bsage.core.events import emit_event

                await emit_event(self._event_bus, "NOTE_UPDATED", {"path": note_path})

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
                note_paths = []

            # Also scan subdirectories (e.g. seeds/telegram-input, garden/insight).
            # read_notes() returns [] (not an exception) when no *.md files exist
            # directly in the directory, so we always check subdirs too.
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
