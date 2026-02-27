"""VectorStore — SQLite + numpy persistent vector storage for vault notes."""

from __future__ import annotations

import asyncio
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

    async def initialize(self) -> None:
        """Create database and table if they don't exist."""

        def _init() -> sqlite3.Connection:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
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
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_init)
        logger.info("vector_store_initialized", db_path=str(self._db_path))

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

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
