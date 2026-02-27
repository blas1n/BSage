"""Tests for bsage.garden.vector_store — SQLite + numpy vector storage."""

import pytest

from bsage.garden.vector_store import NoteEmbedding, VectorStore


@pytest.fixture()
async def store(tmp_path):
    """Create and initialize a VectorStore for testing."""
    db_path = tmp_path / "test.db"
    vs = VectorStore(db_path)
    await vs.initialize()
    yield vs
    await vs.close()


def _record(
    path: str = "garden/idea/note.md",
    embedding: list[float] | None = None,
) -> NoteEmbedding:
    return NoteEmbedding(
        note_path=path,
        content_hash="abc123",
        title="Test Note",
        note_type="idea",
        source="test",
        embedding=embedding or [1.0, 0.0, 0.0],
        indexed_at="2026-02-27T00:00:00",
    )


class TestVectorStoreInit:
    """Test database initialization."""

    async def test_initialize_creates_db(self, tmp_path) -> None:
        db_path = tmp_path / "sub" / "index.db"
        vs = VectorStore(db_path)
        await vs.initialize()
        assert db_path.exists()
        await vs.close()

    async def test_count_empty(self, store) -> None:
        assert await store.count() == 0


class TestVectorStoreUpsert:
    """Test insert and update operations."""

    async def test_upsert_inserts_new(self, store) -> None:
        await store.upsert(_record())
        assert await store.count() == 1

    async def test_upsert_updates_existing(self, store) -> None:
        await store.upsert(_record(embedding=[1.0, 0.0, 0.0]))
        await store.upsert(_record(embedding=[0.0, 1.0, 0.0]))
        assert await store.count() == 1

        # Verify it was actually updated (search should find the new vector)
        results = await store.search([0.0, 1.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0].score > 0.99  # cosine similarity ~1.0

    async def test_upsert_multiple_distinct(self, store) -> None:
        await store.upsert(_record("note1.md", [1.0, 0.0, 0.0]))
        await store.upsert(_record("note2.md", [0.0, 1.0, 0.0]))
        assert await store.count() == 2


class TestVectorStoreSearch:
    """Test cosine similarity search."""

    async def test_search_returns_sorted_by_similarity(self, store) -> None:
        await store.upsert(_record("exact.md", [1.0, 0.0, 0.0]))
        await store.upsert(_record("orthogonal.md", [0.0, 1.0, 0.0]))
        await store.upsert(_record("partial.md", [0.7, 0.7, 0.0]))

        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3
        assert results[0].note_path == "exact.md"
        assert results[0].score > 0.99
        assert results[1].note_path == "partial.md"
        assert results[2].note_path == "orthogonal.md"

    async def test_search_top_k_limit(self, store) -> None:
        for i in range(5):
            await store.upsert(_record(f"note{i}.md", [float(i), 1.0, 0.0]))
        results = await store.search([1.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2

    async def test_search_empty_store(self, store) -> None:
        results = await store.search([1.0, 0.0, 0.0])
        assert results == []

    async def test_search_result_has_metadata(self, store) -> None:
        rec = NoteEmbedding(
            note_path="garden/insight/my-note.md",
            content_hash="hash",
            title="My Insight",
            note_type="insight",
            source="weekly-digest",
            embedding=[1.0, 0.0, 0.0],
            indexed_at="2026-02-27T00:00:00",
        )
        await store.upsert(rec)
        results = await store.search([1.0, 0.0, 0.0], top_k=1)
        assert results[0].title == "My Insight"
        assert results[0].note_type == "insight"
        assert results[0].source == "weekly-digest"


class TestVectorStoreDelete:
    """Test deletion operations."""

    async def test_delete_removes_record(self, store) -> None:
        await store.upsert(_record("to-delete.md"))
        assert await store.count() == 1
        await store.delete("to-delete.md")
        assert await store.count() == 0

    async def test_delete_nonexistent_is_noop(self, store) -> None:
        await store.delete("nonexistent.md")
        assert await store.count() == 0


class TestVectorStoreContentHash:
    """Test content_hash lookup for incremental indexing."""

    async def test_get_hash_returns_stored_hash(self, store) -> None:
        rec = _record()
        await store.upsert(rec)
        h = await store.get_content_hash(rec.note_path)
        assert h == "abc123"

    async def test_get_hash_returns_none_for_missing(self, store) -> None:
        h = await store.get_content_hash("missing.md")
        assert h is None


class TestVectorStoreAllPaths:
    """Test all_paths() for stale entry cleanup."""

    async def test_all_paths_returns_set(self, store) -> None:
        await store.upsert(_record("a.md"))
        await store.upsert(_record("b.md"))
        paths = await store.all_paths()
        assert paths == {"a.md", "b.md"}

    async def test_all_paths_empty(self, store) -> None:
        paths = await store.all_paths()
        assert paths == set()
