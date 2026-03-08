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


# ------------------------------------------------------------------
# FTS5 full-text search
# ------------------------------------------------------------------


class TestVectorStoreFTS:
    """Test FTS5 full-text search features."""

    async def test_fts_table_created_on_init(self, store) -> None:
        assert store.fts_available is True

    async def test_upsert_fts_inserts(self, store) -> None:
        await store.upsert(_record("garden/idea/note.md"))
        await store.upsert_fts("garden/idea/note.md", "My Title", "some body text")
        results = await store.fts_search("body text")
        assert len(results) == 1
        assert results[0].note_path == "garden/idea/note.md"

    async def test_upsert_fts_updates_existing(self, store) -> None:
        await store.upsert(_record("garden/idea/note.md"))
        await store.upsert_fts("garden/idea/note.md", "Old", "old content")
        await store.upsert_fts("garden/idea/note.md", "New", "new content")
        old = await store.fts_search("old content")
        new = await store.fts_search("new content")
        assert len(old) == 0
        assert len(new) == 1

    async def test_delete_fts(self, store) -> None:
        await store.upsert(_record("garden/idea/note.md"))
        await store.upsert_fts("garden/idea/note.md", "Title", "searchable body")
        await store.delete_fts("garden/idea/note.md")
        results = await store.fts_search("searchable body")
        assert len(results) == 0

    async def test_delete_fts_nonexistent_noop(self, store) -> None:
        await store.delete_fts("nonexistent.md")  # no error

    async def test_fts_search_matches_keyword(self, store) -> None:
        await store.upsert(_record("a.md"))
        await store.upsert(_record("b.md", embedding=[0.0, 1.0, 0.0]))
        await store.upsert_fts("a.md", "Alpha", "machine learning research")
        await store.upsert_fts("b.md", "Beta", "cooking recipe guide")
        results = await store.fts_search("machine learning")
        assert len(results) == 1
        assert results[0].note_path == "a.md"

    async def test_fts_search_ranking(self, store) -> None:
        await store.upsert(_record("a.md"))
        await store.upsert(_record("b.md", embedding=[0.0, 1.0, 0.0]))
        await store.upsert_fts("a.md", "Alpha", "python")
        await store.upsert_fts("b.md", "Beta", "python python python programming")
        results = await store.fts_search("python")
        assert len(results) == 2
        # b.md should rank higher (more occurrences)
        assert results[0].note_path == "b.md"

    async def test_fts_search_empty_query(self, store) -> None:
        results = await store.fts_search("")
        assert results == []

    async def test_fts_search_whitespace_query(self, store) -> None:
        results = await store.fts_search("   ")
        assert results == []

    async def test_fts_search_no_match(self, store) -> None:
        await store.upsert(_record("a.md"))
        await store.upsert_fts("a.md", "Title", "some content")
        results = await store.fts_search("nonexistent keyword xyz")
        assert results == []

    async def test_fts_search_joins_metadata(self, store) -> None:
        rec = NoteEmbedding(
            note_path="garden/insight/note.md",
            content_hash="h",
            title="Insight Title",
            note_type="insight",
            source="weekly-digest",
            embedding=[1.0, 0.0, 0.0],
            indexed_at="2026-01-01",
        )
        await store.upsert(rec)
        await store.upsert_fts("garden/insight/note.md", "Insight Title", "deep analysis")
        results = await store.fts_search("deep analysis")
        assert len(results) == 1
        assert results[0].title == "Insight Title"
        assert results[0].note_type == "insight"
        assert results[0].source == "weekly-digest"


# ------------------------------------------------------------------
# Note links
# ------------------------------------------------------------------


class TestVectorStoreLinks:
    """Test note_links table operations."""

    async def test_links_table_created(self, store) -> None:
        # Should be able to insert without error
        await store.upsert_links("a.md", ["b.md"], link_type="explicit")
        linked = await store.get_linked_paths("a.md")
        assert "b.md" in linked

    async def test_upsert_links_and_get(self, store) -> None:
        await store.upsert_links("a.md", ["b.md", "c.md"], link_type="explicit")
        linked = await store.get_linked_paths("a.md")
        assert linked == {"b.md", "c.md"}

    async def test_upsert_links_replaces_by_type(self, store) -> None:
        await store.upsert_links("a.md", ["b.md"], link_type="auto")
        await store.upsert_links("a.md", ["c.md"], link_type="auto")
        linked = await store.get_linked_paths("a.md")
        # auto links replaced: only c.md
        assert "b.md" not in linked
        assert "c.md" in linked

    async def test_upsert_links_different_types_coexist(self, store) -> None:
        await store.upsert_links("a.md", ["b.md"], link_type="explicit")
        await store.upsert_links("a.md", ["c.md"], link_type="auto")
        linked = await store.get_linked_paths("a.md")
        assert linked == {"b.md", "c.md"}

    async def test_delete_links_both_directions(self, store) -> None:
        await store.upsert_links("a.md", ["b.md"])
        await store.upsert_links("c.md", ["a.md"])
        await store.delete_links("a.md")
        # a→b gone
        assert await store.get_linked_paths("a.md") == set()
        # c→a also gone
        assert await store.get_linked_paths("c.md") == set()

    async def test_get_linked_paths_bidirectional(self, store) -> None:
        await store.upsert_links("a.md", ["b.md"])
        # b.md should see a.md as linked (reverse direction)
        linked_from_b = await store.get_linked_paths("b.md")
        assert "a.md" in linked_from_b

    async def test_get_linked_paths_empty(self, store) -> None:
        linked = await store.get_linked_paths("nonexistent.md")
        assert linked == set()


# ------------------------------------------------------------------
# get_embedding
# ------------------------------------------------------------------


class TestVectorStoreGetEmbedding:
    """Test get_embedding() for retrieving stored vectors."""

    async def test_returns_stored_embedding(self, store) -> None:
        await store.upsert(_record("note.md", [0.1, 0.2, 0.3]))
        result = await store.get_embedding("note.md")
        assert result is not None
        assert len(result) == 3
        assert abs(result[0] - 0.1) < 1e-5
        assert abs(result[1] - 0.2) < 1e-5
        assert abs(result[2] - 0.3) < 1e-5

    async def test_returns_none_for_missing(self, store) -> None:
        result = await store.get_embedding("missing.md")
        assert result is None
