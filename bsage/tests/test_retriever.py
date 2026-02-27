"""Tests for bsage.garden.retriever — VaultRetriever semantic search + fallback."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.garden.retriever import (
    VaultRetriever,
    _content_hash,
    _extract_metadata,
    _strip_frontmatter,
)
from bsage.garden.vector_store import SearchResult


def _mock_vault(notes_by_dir: dict[str, list[tuple[str, str]]] | None = None):
    """Create a mock Vault with notes."""
    vault = MagicMock()
    vault.root = Path("/vault")
    notes_by_dir = notes_by_dir or {}

    async def _read_notes(subdir):
        entries = notes_by_dir.get(subdir, [])
        return [Path(f"/vault/{subdir}/{name}") for name, _content in entries]

    async def _read_content(path):
        for entries in notes_by_dir.values():
            for name, content in entries:
                if path.name == name:
                    return content
        raise FileNotFoundError(path)

    def _resolve_path(subpath):
        return Path(f"/vault/{subpath}")

    vault.read_notes = AsyncMock(side_effect=_read_notes)
    vault.read_note_content = AsyncMock(side_effect=_read_content)
    vault.resolve_path = MagicMock(side_effect=_resolve_path)
    return vault


class TestExtractMetadata:
    """Test frontmatter extraction helper."""

    def test_extracts_yaml_frontmatter(self) -> None:
        text = "---\ntitle: Hello\ntype: idea\n---\nBody text"
        meta = _extract_metadata(text)
        assert meta["title"] == "Hello"
        assert meta["type"] == "idea"

    def test_no_frontmatter_returns_empty(self) -> None:
        assert _extract_metadata("No frontmatter here") == {}

    def test_malformed_yaml_returns_empty(self) -> None:
        text = "---\n: bad: yaml:\n---\n"
        result = _extract_metadata(text)
        # yaml.safe_load might parse this as a string, not dict
        assert isinstance(result, dict)

    def test_no_closing_delimiter(self) -> None:
        text = "---\ntitle: Hello\nBody text"
        assert _extract_metadata(text) == {}


class TestStripFrontmatter:
    """Test frontmatter stripping helper."""

    def test_strips_frontmatter(self) -> None:
        text = "---\ntitle: Hello\n---\nBody text"
        assert _strip_frontmatter(text) == "Body text"

    def test_no_frontmatter_returns_original(self) -> None:
        text = "No frontmatter"
        assert _strip_frontmatter(text) == "No frontmatter"


class TestContentHash:
    """Test content hashing."""

    def test_deterministic(self) -> None:
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_content_different_hash(self) -> None:
        assert _content_hash("hello") != _content_hash("world")


class TestVaultRetrieverRAGAvailable:
    """Test rag_available property."""

    def test_rag_available_true(self) -> None:
        retriever = VaultRetriever(
            vault=MagicMock(),
            vector_store=MagicMock(),
            embedding_client=MagicMock(),
        )
        assert retriever.rag_available is True

    def test_rag_available_false_no_store(self) -> None:
        retriever = VaultRetriever(vault=MagicMock(), embedding_client=MagicMock())
        assert retriever.rag_available is False

    def test_rag_available_false_no_client(self) -> None:
        retriever = VaultRetriever(vault=MagicMock(), vector_store=MagicMock())
        assert retriever.rag_available is False

    def test_rag_available_false_none(self) -> None:
        retriever = VaultRetriever(vault=MagicMock())
        assert retriever.rag_available is False


class TestVaultRetrieverFallback:
    """Test fallback (non-RAG) retrieval."""

    async def test_fallback_reads_recent_notes(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [
                    ("01-old.md", "Old content"),
                    ("02-new.md", "New content"),
                ],
            }
        )
        retriever = VaultRetriever(vault=vault)
        result = await retriever.retrieve(query="test", context_dirs=["garden/idea"])
        # reversed order — newest first
        assert result.index("New content") < result.index("Old content")

    async def test_fallback_respects_max_chars(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [("big.md", "x" * 60_000)],
            }
        )
        retriever = VaultRetriever(vault=vault)
        result = await retriever.retrieve(
            query="test", context_dirs=["garden/idea"], max_chars=1000
        )
        assert len(result) <= 1000

    async def test_fallback_empty_vault(self) -> None:
        vault = _mock_vault({})
        retriever = VaultRetriever(vault=vault)
        result = await retriever.retrieve(query="test", context_dirs=["garden/idea"])
        assert result == ""


class TestVaultRetrieverSemantic:
    """Test RAG-based semantic retrieval."""

    async def test_semantic_retrieve(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [("relevant.md", "Relevant content")],
            }
        )
        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[1.0, 0.0, 0.0])

        mock_store = AsyncMock()
        mock_store.search = AsyncMock(
            return_value=[
                SearchResult(
                    note_path="garden/idea/relevant.md",
                    title="Relevant",
                    score=0.95,
                    note_type="idea",
                    source="test",
                ),
            ]
        )

        retriever = VaultRetriever(
            vault=vault,
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )
        result = await retriever.retrieve(
            query="find relevant notes",
            context_dirs=["garden/idea"],
        )
        assert "Relevant content" in result
        mock_embedding.embed_one.assert_called_once()

    async def test_semantic_filters_by_context_dirs(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [("note.md", "Idea content")],
            }
        )
        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[1.0, 0.0, 0.0])

        mock_store = AsyncMock()
        mock_store.search = AsyncMock(
            return_value=[
                SearchResult("garden/idea/note.md", "Note", 0.9, "idea", "test"),
                SearchResult("seeds/chat/other.md", "Other", 0.8, "seed", "chat"),
            ]
        )

        retriever = VaultRetriever(
            vault=vault,
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )
        result = await retriever.retrieve(
            query="test",
            context_dirs=["garden/idea"],
        )
        # Only garden/idea should be included
        assert "Idea content" in result

    async def test_semantic_falls_back_on_error(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [("fallback.md", "Fallback content")],
            }
        )
        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(side_effect=RuntimeError("API error"))

        retriever = VaultRetriever(
            vault=vault,
            vector_store=AsyncMock(),
            embedding_client=mock_embedding,
        )
        result = await retriever.retrieve(
            query="test",
            context_dirs=["garden/idea"],
        )
        # Should fall back to recency-based retrieval
        assert "Fallback content" in result

    async def test_semantic_no_results_falls_back(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [("note.md", "Some content")],
            }
        )
        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[1.0, 0.0, 0.0])

        mock_store = AsyncMock()
        mock_store.search = AsyncMock(return_value=[])

        retriever = VaultRetriever(
            vault=vault,
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )
        result = await retriever.retrieve(
            query="test",
            context_dirs=["garden/idea"],
        )
        assert "Some content" in result


class TestVaultRetrieverIndexNote:
    """Test index_note() for write-time indexing."""

    async def test_index_note_creates_embedding(self) -> None:
        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[0.1, 0.2, 0.3])

        mock_store = AsyncMock()
        mock_store.get_content_hash = AsyncMock(return_value=None)
        mock_store.upsert = AsyncMock()

        retriever = VaultRetriever(
            vault=MagicMock(),
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )

        content = "---\ntitle: My Note\ntype: idea\nsource: chat\n---\nNote body"
        await retriever.index_note("garden/idea/my-note.md", content)

        mock_store.upsert.assert_called_once()
        record = mock_store.upsert.call_args.args[0]
        assert record.note_path == "garden/idea/my-note.md"
        assert record.title == "My Note"
        assert record.note_type == "idea"
        assert record.embedding == [0.1, 0.2, 0.3]

    async def test_index_note_skips_unchanged(self) -> None:
        content = "Some content"
        c_hash = _content_hash(content)

        mock_store = AsyncMock()
        mock_store.get_content_hash = AsyncMock(return_value=c_hash)

        retriever = VaultRetriever(
            vault=MagicMock(),
            vector_store=mock_store,
            embedding_client=AsyncMock(),
        )
        await retriever.index_note("note.md", content)

        # embed should not be called since hash matches
        mock_store.upsert.assert_not_called()

    async def test_index_note_noop_when_rag_unavailable(self) -> None:
        retriever = VaultRetriever(vault=MagicMock())
        # Should not raise
        await retriever.index_note("note.md", "content")

    async def test_index_note_handles_embedding_failure(self) -> None:
        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(side_effect=RuntimeError("API error"))

        mock_store = AsyncMock()
        mock_store.get_content_hash = AsyncMock(return_value=None)

        retriever = VaultRetriever(
            vault=MagicMock(),
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )
        # Should not raise
        await retriever.index_note("note.md", "content")
        mock_store.upsert.assert_not_called()


class TestVaultRetrieverReindexAll:
    """Test reindex_all() for full vault reindexing."""

    async def test_reindex_all_raises_when_rag_unavailable(self) -> None:
        retriever = VaultRetriever(vault=MagicMock())
        with pytest.raises(RuntimeError, match="RAG not available"):
            await retriever.reindex_all()

    async def test_reindex_all_indexes_notes(self) -> None:
        vault = _mock_vault(
            {
                "seeds/chat": [("2026-02-27_0900.md", "Seed content")],
                "garden/idea": [("note.md", "Garden content")],
            }
        )
        # Make resolve_path return real-like paths and handle subdirectory iteration
        vault.resolve_path = MagicMock(side_effect=lambda p: Path(f"/vault/{p}"))

        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[0.1, 0.2, 0.3])

        mock_store = AsyncMock()
        mock_store.get_content_hash = AsyncMock(return_value=None)
        mock_store.upsert = AsyncMock()
        mock_store.all_paths = AsyncMock(return_value=set())

        retriever = VaultRetriever(
            vault=vault,
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )

        # reindex_all tries read_notes on "seeds" and "garden" first,
        # then iterates subdirectories if those fail.
        # We mock read_notes to return results for the subdirs.
        count = await retriever.reindex_all(dirs=["seeds/chat", "garden/idea"])
        assert count == 2

    async def test_reindex_all_cleans_stale_entries(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [("current.md", "Current content")],
            }
        )
        vault.resolve_path = MagicMock(side_effect=lambda p: Path(f"/vault/{p}"))

        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[0.1])

        mock_store = AsyncMock()
        mock_store.get_content_hash = AsyncMock(return_value=None)
        mock_store.upsert = AsyncMock()
        mock_store.all_paths = AsyncMock(
            return_value={"garden/idea/current.md", "garden/idea/deleted.md"}
        )
        mock_store.delete = AsyncMock()

        retriever = VaultRetriever(
            vault=vault,
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )
        await retriever.reindex_all(dirs=["garden/idea"])

        mock_store.delete.assert_called_once_with("garden/idea/deleted.md")

    async def test_reindex_all_reports_progress(self) -> None:
        vault = _mock_vault(
            {
                "garden/idea": [
                    ("a.md", "A"),
                    ("b.md", "B"),
                ],
            }
        )
        vault.resolve_path = MagicMock(side_effect=lambda p: Path(f"/vault/{p}"))

        mock_embedding = AsyncMock()
        mock_embedding.embed_one = AsyncMock(return_value=[0.1])

        mock_store = AsyncMock()
        mock_store.get_content_hash = AsyncMock(return_value=None)
        mock_store.upsert = AsyncMock()
        mock_store.all_paths = AsyncMock(return_value=set())

        retriever = VaultRetriever(
            vault=vault,
            vector_store=mock_store,
            embedding_client=mock_embedding,
        )

        progress_calls: list[tuple[int, int]] = []
        await retriever.reindex_all(
            dirs=["garden/idea"],
            on_progress=lambda c, t: progress_calls.append((c, t)),
        )
        assert len(progress_calls) == 2
        assert progress_calls[-1] == (2, 2)
