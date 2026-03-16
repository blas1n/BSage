"""Tests for VaultRetriever semantic (vector) search."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.garden.index_reader import NoteSummary
from bsage.garden.retriever import VaultRetriever


@pytest.fixture()
def mock_vault(tmp_path):
    vault = MagicMock()
    vault.root = tmp_path / "vault"
    vault.root.mkdir()
    return vault


@pytest.fixture()
def mock_embedder():
    e = MagicMock()
    e.enabled = True
    e.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])
    return e


@pytest.fixture()
def mock_vector_store():
    vs = AsyncMock()
    vs.search = AsyncMock(
        return_value=[
            ("garden/idea/best.md", 0.95),
            ("garden/idea/good.md", 0.80),
            ("seeds/other.md", 0.60),
        ]
    )
    return vs


@pytest.fixture()
def mock_index_reader():
    ir = AsyncMock()
    ir.get_all_summaries = AsyncMock(
        return_value=[
            NoteSummary(
                path="garden/idea/best.md",
                title="Best Match",
                note_type="idea",
                tags=["ai"],
                captured_at="2026-03-15",
            ),
            NoteSummary(
                path="garden/idea/good.md",
                title="Good Match",
                note_type="idea",
                tags=[],
                captured_at="2026-03-14",
            ),
        ]
    )
    return ir


class TestVectorSearch:
    async def test_vector_search_returns_ranked_results(
        self, mock_vault, mock_embedder, mock_vector_store, mock_index_reader
    ) -> None:
        retriever = VaultRetriever(
            vault=mock_vault,
            index_reader=mock_index_reader,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )

        result = await retriever.search("AI concepts")

        assert "semantic similarity" in result
        assert "Best Match" in result
        assert "Good Match" in result
        assert "0.95" in result or "0.950" in result
        mock_embedder.embed.assert_awaited_once_with("AI concepts")

    async def test_vector_search_filters_by_context_dirs(
        self, mock_vault, mock_embedder, mock_vector_store, mock_index_reader
    ) -> None:
        retriever = VaultRetriever(
            vault=mock_vault,
            index_reader=mock_index_reader,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )

        result = await retriever.search("query", context_dirs=["garden/idea"])

        # seeds/other.md should be filtered out
        assert "other.md" not in result
        assert "Best Match" in result

    async def test_falls_back_when_no_vector_store(self, mock_vault, mock_index_reader) -> None:
        retriever = VaultRetriever(
            vault=mock_vault,
            index_reader=mock_index_reader,
        )

        result = await retriever.search("query")

        # Should use index-based search, not vector
        assert "semantic similarity" not in result
        mock_index_reader.get_all_summaries.assert_awaited()

    async def test_falls_back_when_embedder_disabled(
        self, mock_vault, mock_vector_store, mock_index_reader
    ) -> None:
        disabled_embedder = MagicMock()
        disabled_embedder.enabled = False

        retriever = VaultRetriever(
            vault=mock_vault,
            index_reader=mock_index_reader,
            vector_store=mock_vector_store,
            embedder=disabled_embedder,
        )

        result = await retriever.search("query")
        assert "semantic similarity" not in result

    async def test_falls_back_on_embed_error(
        self, mock_vault, mock_vector_store, mock_index_reader
    ) -> None:
        error_embedder = MagicMock()
        error_embedder.enabled = True
        error_embedder.embed = AsyncMock(side_effect=RuntimeError("API down"))

        retriever = VaultRetriever(
            vault=mock_vault,
            index_reader=mock_index_reader,
            vector_store=mock_vector_store,
            embedder=error_embedder,
        )

        result = await retriever.search("query")

        # Should fall back to index-based search
        assert "semantic similarity" not in result
        mock_index_reader.get_all_summaries.assert_awaited()

    async def test_vector_search_with_graph_retriever(
        self, mock_vault, mock_embedder, mock_vector_store, mock_index_reader
    ) -> None:
        mock_graph = AsyncMock()
        mock_graph.retrieve = AsyncMock(return_value="Graph: Related entities found")

        retriever = VaultRetriever(
            vault=mock_vault,
            index_reader=mock_index_reader,
            graph_retriever=mock_graph,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )

        result = await retriever.search("query")

        assert "semantic similarity" in result
        assert "Graph: Related entities found" in result
