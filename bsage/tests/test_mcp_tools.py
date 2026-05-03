"""Tests for bsage.gateway.mcp_tools — transport-agnostic MCP tool core.

These functions take (state, params) and return dicts, callable from
both REST handlers and the MCP stdio/SSE transports without FastAPI coupling.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.gateway import mcp_tools


@pytest.fixture()
def state() -> MagicMock:
    """Minimal AppState mock for tool functions (no FastAPI dependency)."""
    s = MagicMock()
    s.vault = MagicMock()
    s.vault.root = Path("/vault")
    s.vault.resolve_path = MagicMock(side_effect=lambda p: Path(f"/vault/{p}"))
    s.vault.read_note_content = AsyncMock(return_value="---\ntags: [test]\n---\n# Note\nBody text")
    s.embedder = MagicMock()
    s.embedder.enabled = False
    s.vector_store = None
    s.retriever = MagicMock()
    s.retriever.search = AsyncMock(return_value="Found 2 notes")
    s.graph_retriever = MagicMock()
    s.graph_retriever.retrieve = AsyncMock(return_value="## Graph\nEntity: X")
    s.index_reader = MagicMock()
    s.index_reader.get_all_summaries = AsyncMock(
        return_value=[
            MagicMock(
                title="Note A",
                path="garden/idea/a.md",
                tags=["t1"],
                captured_at="2026-05-01",
                note_type="idea",
            ),
            MagicMock(
                title="Note B",
                path="garden/insight/b.md",
                tags=[],
                captured_at="2026-05-02",
                note_type="insight",
            ),
        ]
    )
    s.garden_writer = MagicMock()
    s.garden_writer.write_garden = AsyncMock(return_value=Path("/vault/garden/idea/foo.md"))
    return s


# -- search_knowledge ---------------------------------------------------------


class TestSearchKnowledge:
    @pytest.mark.asyncio
    async def test_returns_results_via_retriever_when_no_vector_store(
        self, state: MagicMock
    ) -> None:
        result = await mcp_tools.search_knowledge(state, {"query": "python", "top_k": 5})
        assert result["query"] == "python"
        assert isinstance(result["results"], list)
        assert len(result["results"]) >= 1

    @pytest.mark.asyncio
    async def test_uses_vector_store_when_enabled(self, state: MagicMock) -> None:
        state.embedder.enabled = True
        state.embedder.embed = AsyncMock(return_value=[0.1, 0.2])
        state.vector_store = MagicMock()
        state.vector_store.search = AsyncMock(return_value=[("garden/idea/a.md", 0.92)])

        result = await mcp_tools.search_knowledge(state, {"query": "x"})
        assert len(result["results"]) == 1
        assert result["results"][0]["score"] == pytest.approx(0.92, abs=1e-3)
        assert result["results"][0]["path"] == "garden/idea/a.md"

    @pytest.mark.asyncio
    async def test_default_top_k(self, state: MagicMock) -> None:
        result = await mcp_tools.search_knowledge(state, {"query": "any"})
        assert "results" in result
        # retriever called with top_k=10 default
        state.retriever.search.assert_awaited_once()
        _, kwargs = state.retriever.search.call_args
        assert kwargs.get("top_k") == 10


# -- get_note -----------------------------------------------------------------


class TestGetNote:
    @pytest.mark.asyncio
    async def test_returns_path_and_content(self, state: MagicMock) -> None:
        resolved = MagicMock(spec=Path)
        resolved.is_file.return_value = True
        state.vault.resolve_path = MagicMock(return_value=resolved)

        result = await mcp_tools.get_note(state, {"path": "garden/idea/a.md"})
        assert result["path"] == "garden/idea/a.md"
        assert "Body text" in result["content"]

    @pytest.mark.asyncio
    async def test_raises_when_file_not_found(self, state: MagicMock) -> None:
        resolved = MagicMock(spec=Path)
        resolved.is_file.return_value = False
        state.vault.resolve_path = MagicMock(return_value=resolved)

        with pytest.raises(FileNotFoundError):
            await mcp_tools.get_note(state, {"path": "missing.md"})


# -- get_graph_context --------------------------------------------------------


class TestGetGraphContext:
    @pytest.mark.asyncio
    async def test_returns_context_for_topic(self, state: MagicMock) -> None:
        result = await mcp_tools.get_graph_context(state, {"topic": "Python"})
        assert result["topic"] == "Python"
        assert result["has_results"] is True
        assert "Graph" in result["context"]

    @pytest.mark.asyncio
    async def test_empty_context_returns_no_results(self, state: MagicMock) -> None:
        state.graph_retriever.retrieve = AsyncMock(return_value="")
        result = await mcp_tools.get_graph_context(state, {"topic": "x"})
        assert result["has_results"] is False
        assert "No graph context" in result["context"]

    @pytest.mark.asyncio
    async def test_raises_when_graph_unavailable(self, state: MagicMock) -> None:
        state.graph_retriever = None
        with pytest.raises(RuntimeError):
            await mcp_tools.get_graph_context(state, {"topic": "x"})


# -- list_recent --------------------------------------------------------------


class TestListRecent:
    @pytest.mark.asyncio
    async def test_returns_catalog_grouped_by_type(self, state: MagicMock) -> None:
        result = await mcp_tools.list_recent(state, {})
        assert result["total"] == 2
        assert "idea" in result["categories"]
        assert "insight" in result["categories"]
        assert result["categories"]["idea"][0]["title"] == "Note A"


# -- create_note --------------------------------------------------------------


class TestCreateNote:
    @pytest.mark.asyncio
    async def test_writes_via_garden_writer(self, state: MagicMock) -> None:
        result = await mcp_tools.create_note(
            state,
            {
                "title": "Hello",
                "content": "Body",
                "note_type": "idea",
                "source": "mcp",
                "tags": ["t1"],
            },
        )
        state.garden_writer.write_garden.assert_awaited_once()
        called = state.garden_writer.write_garden.call_args[0][0]
        assert called.title == "Hello"
        assert called.content == "Body"
        assert called.note_type == "idea"
        assert called.source == "mcp"
        assert called.tags == ["t1"]
        assert "path" in result
        assert "id" in result

    @pytest.mark.asyncio
    async def test_appends_wikilinks_when_links_provided(self, state: MagicMock) -> None:
        await mcp_tools.create_note(
            state,
            {
                "title": "T",
                "content": "Body",
                "links": ["Other Note", "Second"],
            },
        )
        called = state.garden_writer.write_garden.call_args[0][0]
        assert "[[Other Note]]" in called.content
        assert "[[Second]]" in called.content

    @pytest.mark.asyncio
    async def test_passes_tenant_id_from_principal(self, state: MagicMock) -> None:
        principal = MagicMock()
        principal.tenant_id = "tenant-7"

        await mcp_tools.create_note(
            state,
            {"title": "T", "content": "B"},
            principal=principal,
        )
        called = state.garden_writer.write_garden.call_args[0][0]
        assert called.tenant_id == "tenant-7"
