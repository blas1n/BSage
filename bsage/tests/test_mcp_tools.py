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
    s.garden_writer.write_seed = AsyncMock(return_value=Path("/vault/seeds/mcp/foo.md"))
    s.ingest_compiler = MagicMock()
    s.ingest_compiler.compile = AsyncMock(return_value=MagicMock(notes_created=1, notes_updated=0))
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
    async def test_returns_catalog_grouped_by_maturity(self, state: MagicMock) -> None:
        # Step B5: list_recent now groups by maturity instead of note_type.
        # The fixture summaries live under legacy ``garden/idea/`` paths,
        # which means there's no maturity prefix in the path — they fall
        # into the "unfiled" bucket. That's the contract: legacy notes
        # show up but signal that they need migration.
        result = await mcp_tools.list_recent(state, {})
        assert result["total"] == 2
        assert "unfiled" in result["categories"]
        assert {entry["title"] for entry in result["categories"]["unfiled"]} == {
            "Note A",
            "Note B",
        }


# -- create_note --------------------------------------------------------------


class TestCreateNote:
    """create_note submits a SEED + invokes IngestCompiler.

    External MCP callers can no longer write garden notes directly —
    classification + linking is owned by IngestCompiler. The tool
    itself returns the seed path plus compile counts so the caller
    can confirm what changed.
    """

    @pytest.mark.asyncio
    async def test_writes_a_seed_then_invokes_compiler(self, state: MagicMock) -> None:
        result = await mcp_tools.create_note(
            state,
            {
                "title": "Hello",
                "content": "Body",
                "source": "mcp",
                "tags": ["t1"],
            },
        )
        state.garden_writer.write_seed.assert_awaited_once()
        seed_source, seed_data = state.garden_writer.write_seed.call_args[0]
        assert seed_source == "mcp/mcp"
        assert seed_data["title"] == "Hello"
        assert seed_data["content"] == "Body"
        assert seed_data["tags"] == ["t1"]
        assert seed_data["provenance"]["submitted_via"] == "mcp"

        state.ingest_compiler.compile.assert_awaited_once()
        assert "seed_path" in result
        assert result["notes_created"] == 1
        assert result["compiler_available"] is True

    @pytest.mark.asyncio
    async def test_garden_writer_write_garden_is_never_called(self, state: MagicMock) -> None:
        # Add the attribute with a tracking mock so we can assert it
        # stays untouched. Regression guard against a refactor that
        # reintroduces a direct garden write from MCP.
        sentinel = AsyncMock()
        state.garden_writer.write_garden = sentinel
        await mcp_tools.create_note(state, {"title": "X", "content": "Y"})
        sentinel.assert_not_awaited()

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
        seed_data = state.garden_writer.write_seed.call_args[0][1]
        assert "[[Other Note]]" in seed_data["content"]
        assert "[[Second]]" in seed_data["content"]

    @pytest.mark.asyncio
    async def test_stamps_tenant_id_from_principal(self, state: MagicMock) -> None:
        principal = MagicMock()
        principal.tenant_id = "tenant-7"

        await mcp_tools.create_note(
            state,
            {"title": "T", "content": "B"},
            principal=principal,
        )
        seed_data = state.garden_writer.write_seed.call_args[0][1]
        assert seed_data["tenant_id"] == "tenant-7"

    @pytest.mark.asyncio
    async def test_runs_without_compiler(self, state: MagicMock) -> None:
        state.ingest_compiler = None
        result = await mcp_tools.create_note(state, {"title": "T", "content": "B"})
        assert result["compiler_available"] is False
        assert result["notes_created"] == 0
        assert "seed_path" in result
