"""VectorStore — SQLite + numpy persistent vector storage for vault notes."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class NoteEmbedding:
    """A single indexed note record."""

    note_path: str
    content_hash: str
    title: str
    note_type: str
    source: str
    embedding: list[float]
    indexed_at: str


@dataclass
class SearchResult:
    """A vector similarity search result."""

    note_path: str
    title: str
    score: float
    note_type: str
    source: str


class VectorStore:
    """SQLite-backed persistent vector store with numpy cosine similarity.

    Embeddings are stored as raw float32 bytes via ``numpy.tobytes()``
    for compact storage and fast deserialization.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._fts_available: bool = False
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create database and table if they don't exist."""

        def _init() -> tuple[sqlite3.Connection, bool]:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    note_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    note_type TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    embedding BLOB NOT NULL,
                    dimensions INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                )
                """
            )

            # FTS5 full-text search (graceful degradation if unavailable)
            fts_ok = False
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
                        note_path UNINDEXED,
                        title,
                        body,
                        tokenize='unicode61'
                    )
                    """
                )
                fts_ok = True
            except Exception:
                pass

            # Note links table (explicit wiki-links + auto similarity links)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS note_links (
                    source_path TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    link_type TEXT NOT NULL DEFAULT 'explicit',
                    PRIMARY KEY (source_path, target_path)
                )
                """
            )

            conn.commit()
            return conn, fts_ok

        self._conn, self._fts_available = await asyncio.to_thread(_init)
        logger.info(
            "vector_store_initialized",
            db_path=str(self._db_path),
            fts_available=self._fts_available,
        )

    async def upsert(self, record: NoteEmbedding) -> None:
        """Insert or update an embedding record."""
        vec = np.array(record.embedding, dtype=np.float32)

        def _upsert() -> None:
            assert self._conn is not None
            self._conn.execute(
                """INSERT OR REPLACE INTO embeddings
                   (note_path, content_hash, title, note_type, source,
                    embedding, dimensions, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.note_path,
                    record.content_hash,
                    record.title,
                    record.note_type,
                    record.source,
                    vec.tobytes(),
                    len(record.embedding),
                    record.indexed_at,
                ),
            )
            self._conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_upsert)

    async def search(self, query_vector: list[float], top_k: int = 10) -> list[SearchResult]:
        """Find the top-k most similar notes by cosine similarity."""
        qvec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(qvec)
        if q_norm > 0:
            qvec = qvec / q_norm

        def _search() -> list[SearchResult]:
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT note_path, title, note_type, source, embedding, dimensions FROM embeddings"
            ).fetchall()
            if not rows:
                return []

            results: list[SearchResult] = []
            for note_path, title, note_type, source, emb_bytes, _dims in rows:
                vec = np.frombuffer(emb_bytes, dtype=np.float32).copy()
                v_norm = np.linalg.norm(vec)
                if v_norm > 0:
                    vec = vec / v_norm
                score = float(np.dot(qvec, vec))
                results.append(
                    SearchResult(
                        note_path=note_path,
                        title=title,
                        score=score,
                        note_type=note_type,
                        source=source,
                    )
                )
            results.sort(key=lambda r: r.score, reverse=True)
            return results[:top_k]

        return await asyncio.to_thread(_search)

    async def get_content_hash(self, note_path: str) -> str | None:
        """Return the stored content_hash for a note, or None if not indexed."""

        def _get() -> str | None:
            assert self._conn is not None
            row = self._conn.execute(
                "SELECT content_hash FROM embeddings WHERE note_path = ?",
                (note_path,),
            ).fetchone()
            return row[0] if row else None

        return await asyncio.to_thread(_get)

    async def delete(self, note_path: str) -> None:
        """Remove an embedding record."""

        def _delete() -> None:
            assert self._conn is not None
            self._conn.execute("DELETE FROM embeddings WHERE note_path = ?", (note_path,))
            self._conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_delete)

    async def count(self) -> int:
        """Return the number of indexed notes."""

        def _count() -> int:
            assert self._conn is not None
            row = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
            return row[0] if row else 0

        return await asyncio.to_thread(_count)

    async def all_paths(self) -> set[str]:
        """Return set of all indexed note paths."""

        def _all() -> set[str]:
            assert self._conn is not None
            rows = self._conn.execute("SELECT note_path FROM embeddings").fetchall()
            return {r[0] for r in rows}

        return await asyncio.to_thread(_all)

    async def get_embedding(self, note_path: str) -> list[float] | None:
        """Return the stored embedding vector for a note, or None if not indexed."""
        conn = self._conn
        if conn is None:
            return None

        def _get() -> list[float] | None:
            row = conn.execute(
                "SELECT embedding FROM embeddings WHERE note_path = ?",
                (note_path,),
            ).fetchone()
            if not row:
                return None
            return np.frombuffer(row[0], dtype=np.float32).tolist()

        return await asyncio.to_thread(_get)

    # ------------------------------------------------------------------
    # FTS5 full-text search
    # ------------------------------------------------------------------

    @property
    def fts_available(self) -> bool:
        """True if FTS5 was successfully initialized."""
        return self._fts_available

    async def upsert_fts(self, note_path: str, title: str, body: str) -> None:
        """Insert or replace a note in the FTS5 index."""
        conn = self._conn
        if conn is None:
            return

        def _upsert() -> None:
            conn.execute("DELETE FROM note_fts WHERE note_path = ?", (note_path,))
            conn.execute(
                "INSERT INTO note_fts (note_path, title, body) VALUES (?, ?, ?)",
                (note_path, title, body),
            )
            conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_upsert)

    async def delete_fts(self, note_path: str) -> None:
        """Remove a note from the FTS5 index."""
        conn = self._conn
        if conn is None:
            return

        def _delete() -> None:
            conn.execute("DELETE FROM note_fts WHERE note_path = ?", (note_path,))
            conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_delete)

    async def fts_search(self, query: str, top_k: int = 20) -> list[SearchResult]:
        """Full-text keyword search using FTS5 BM25 ranking.

        Returns results ordered by relevance. Empty or whitespace-only
        queries return an empty list.
        """
        if not query or not query.strip():
            return []

        conn = self._conn
        if conn is None:
            return []

        def _search() -> list[SearchResult]:
            # Strip FTS5 operators for safe matching; preserve hyphens (common
            # in wiki-link names like ``project-x``).  Double-quoting each
            # token already prevents operator injection.
            tokens = [re.sub(r"[^\w-]", "", t).strip("-") for t in query.split()]
            tokens = [t for t in tokens if t]
            if not tokens:
                return []
            safe_query = " ".join('"' + t + '"' for t in tokens)
            try:
                rows = conn.execute(
                    """
                    SELECT f.note_path, e.title, e.note_type, e.source, f.rank
                    FROM note_fts f
                    JOIN embeddings e ON f.note_path = e.note_path
                    WHERE note_fts MATCH ?
                    ORDER BY f.rank
                    LIMIT ?
                    """,
                    (safe_query, top_k),
                ).fetchall()
            except sqlite3.OperationalError:
                return []

            return [
                SearchResult(
                    note_path=r[0],
                    title=r[1],
                    score=-r[4],  # FTS5 rank is negative; negate for consistency
                    note_type=r[2],
                    source=r[3],
                )
                for r in rows
            ]

        return await asyncio.to_thread(_search)

    # ------------------------------------------------------------------
    # Note links (explicit wiki-links + auto similarity links)
    # ------------------------------------------------------------------

    async def upsert_links(
        self, source_path: str, targets: list[str], link_type: str = "explicit"
    ) -> None:
        """Replace all links of a given type from *source_path*."""

        conn = self._conn
        if conn is None:
            return

        def _upsert() -> None:
            conn.execute(
                "DELETE FROM note_links WHERE source_path = ? AND link_type = ?",
                (source_path, link_type),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO note_links (source_path, target_path, link_type) "
                "VALUES (?, ?, ?)",
                [(source_path, t, link_type) for t in targets],
            )
            conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_upsert)

    async def delete_links(self, note_path: str) -> None:
        """Remove all links involving *note_path* (both directions)."""
        conn = self._conn
        if conn is None:
            return

        def _delete() -> None:
            conn.execute(
                "DELETE FROM note_links WHERE source_path = ? OR target_path = ?",
                (note_path, note_path),
            )
            conn.commit()

        async with self._write_lock:
            await asyncio.to_thread(_delete)

    async def get_linked_paths_batch(self, note_paths: list[str]) -> dict[str, set[str]]:
        """Return linked paths for multiple notes in a single query."""
        conn = self._conn
        if conn is None:
            return {}

        def _get() -> dict[str, set[str]]:
            if not note_paths:
                return {}
            # Placeholders are safe — only the count is dynamic, values are
            # passed as parameterized ``?`` bindings.
            placeholders = ",".join("?" * len(note_paths))
            rows = conn.execute(
                f"""
                SELECT source_path, target_path FROM note_links
                WHERE source_path IN ({placeholders})
                UNION
                SELECT target_path, source_path FROM note_links
                WHERE target_path IN ({placeholders})
                """,
                note_paths + note_paths,
            ).fetchall()
            result: dict[str, set[str]] = {p: set() for p in note_paths}
            for src, tgt in rows:
                if src in result:
                    result[src].add(tgt)
            return result

        return await asyncio.to_thread(_get)

    async def get_linked_paths(self, note_path: str) -> set[str]:
        """Return all paths linked from or to *note_path*."""
        conn = self._conn
        if conn is None:
            return set()

        def _get() -> set[str]:
            rows = conn.execute(
                """
                SELECT target_path FROM note_links WHERE source_path = ?
                UNION
                SELECT source_path FROM note_links WHERE target_path = ?
                """,
                (note_path, note_path),
            ).fetchall()
            return {r[0] for r in rows}

        return await asyncio.to_thread(_get)

    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
