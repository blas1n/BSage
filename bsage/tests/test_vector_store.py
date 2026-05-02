"""Tests for VectorStore — SQLite-backed vector embedding storage."""

import asyncio
import math

import pytest

from bsage.garden.vector_store import (
    VectorStore,
    _cosine_similarity,
    _pack_embedding,
    _unpack_embedding,
)


@pytest.fixture()
async def store(tmp_path):
    db_path = tmp_path / "vectors.db"
    s = VectorStore(db_path)
    await s.initialize()
    yield s
    await s.close()


class TestPackUnpack:
    def test_round_trip(self) -> None:
        vec = [1.0, 2.0, 3.0, -0.5]
        blob = _pack_embedding(vec)
        result = _unpack_embedding(blob, len(vec))
        for a, b in zip(vec, result, strict=True):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self) -> None:
        blob = _pack_embedding([])
        result = _unpack_embedding(blob, 0)
        assert result == []


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 1e-6

    def test_zero_vector(self) -> None:
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_known_similarity(self) -> None:
        a = [1.0, 1.0]
        b = [1.0, 0.0]
        expected = 1.0 / math.sqrt(2)
        assert abs(_cosine_similarity(a, b) - expected) < 1e-6


class TestVectorStore:
    async def test_store_and_count(self, store: VectorStore) -> None:
        await store.store("note/a.md", [1.0, 2.0, 3.0])
        assert await store.count() == 1

    async def test_store_upsert(self, store: VectorStore) -> None:
        await store.store("note/a.md", [1.0, 2.0, 3.0])
        await store.store("note/a.md", [4.0, 5.0, 6.0])
        assert await store.count() == 1

    async def test_has_embedding(self, store: VectorStore) -> None:
        assert not await store.has_embedding("note/a.md")
        await store.store("note/a.md", [1.0, 2.0])
        assert await store.has_embedding("note/a.md")

    async def test_remove(self, store: VectorStore) -> None:
        await store.store("note/a.md", [1.0, 2.0])
        await store.remove("note/a.md")
        assert await store.count() == 0

    async def test_remove_nonexistent(self, store: VectorStore) -> None:
        await store.remove("nonexistent.md")
        assert await store.count() == 0

    async def test_search_returns_ranked_results(self, store: VectorStore) -> None:
        await store.store("exact.md", [1.0, 0.0, 0.0])
        await store.store("similar.md", [0.9, 0.1, 0.0])
        await store.store("different.md", [0.0, 0.0, 1.0])

        results = await store.search([1.0, 0.0, 0.0], top_k=3)

        assert len(results) == 3
        assert results[0][0] == "exact.md"
        assert results[0][1] > results[1][1] > results[2][1]

    async def test_search_top_k(self, store: VectorStore) -> None:
        for i in range(5):
            await store.store(f"note/{i}.md", [float(i), 1.0])

        results = await store.search([4.0, 1.0], top_k=2)
        assert len(results) == 2

    async def test_search_empty_store(self, store: VectorStore) -> None:
        results = await store.search([1.0, 2.0], top_k=5)
        assert results == []

    async def test_not_initialized_raises(self, tmp_path) -> None:
        s = VectorStore(tmp_path / "new.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            await s.store("a.md", [1.0])


# Sprint 3 — concurrent write regression (S3-4 / G4)
async def test_concurrent_store_no_lock_errors(store: VectorStore) -> None:
    """100 concurrent ``store()`` calls must all succeed under the queue."""
    n = 100

    async def write_one(i: int) -> None:
        await store.store(f"note/{i:03d}.md", [float(i), 1.0])

    results = await asyncio.gather(
        *(write_one(i) for i in range(n)),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == []
    assert await store.count() == n
