"""Tests for the dynamic-ontology MCP tools (Step B5).

The new ``list_by_tag`` / ``list_tags`` / ``browse_communities`` /
``browse_entity`` tools, plus the maturity-based ``list_recent``
grouping, are how external LLMs (Claude Desktop etc.) navigate a
post-refactor vault. These tests pin the response shape so the MCP
contract doesn't drift silently.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.gateway import mcp_tools


def _summary(
    *,
    title: str,
    path: str,
    tags: list[str] | None = None,
    captured_at: str | None = None,
    maturity: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        path=path,
        tags=tags or [],
        captured_at=captured_at,
        maturity=maturity,
    )


def _state(*, summaries: list[Any] | None = None, **extra: Any) -> SimpleNamespace:
    index_reader = SimpleNamespace(get_all_summaries=AsyncMock(return_value=summaries or []))
    return SimpleNamespace(index_reader=index_reader, **extra)


class TestListRecentGroupsByMaturity:
    @pytest.mark.asyncio
    async def test_groups_by_explicit_maturity_field(self) -> None:
        state = _state(
            summaries=[
                _summary(title="A", path="garden/seedling/a.md", maturity="seedling"),
                _summary(title="B", path="garden/budding/b.md", maturity="budding"),
                _summary(title="C", path="garden/evergreen/c.md", maturity="evergreen"),
            ]
        )
        result = await mcp_tools.list_recent(state, {})
        assert set(result["categories"].keys()) == {"seedling", "budding", "evergreen"}
        assert result["total"] == 3

    @pytest.mark.asyncio
    async def test_falls_back_to_path_when_maturity_missing(self) -> None:
        state = _state(summaries=[_summary(title="A", path="garden/budding/a.md")])
        result = await mcp_tools.list_recent(state, {})
        assert "budding" in result["categories"]

    @pytest.mark.asyncio
    async def test_legacy_path_lands_in_unfiled(self) -> None:
        state = _state(summaries=[_summary(title="Legacy", path="ideas/legacy.md")])
        result = await mcp_tools.list_recent(state, {})
        assert "unfiled" in result["categories"]


class TestListByTag:
    @pytest.mark.asyncio
    async def test_any_match_default_returns_union(self) -> None:
        state = _state(
            summaries=[
                _summary(title="A", path="garden/seedling/a.md", tags=["python", "tooling"]),
                _summary(title="B", path="garden/seedling/b.md", tags=["python"]),
                _summary(title="C", path="garden/seedling/c.md", tags=["unrelated"]),
            ]
        )
        result = await mcp_tools.list_by_tag(state, {"tags": ["python"]})
        assert result["match"] == "any"
        assert result["total"] == 2
        titles = {r["title"] for r in result["results"]}
        assert titles == {"A", "B"}

    @pytest.mark.asyncio
    async def test_all_match_returns_intersection(self) -> None:
        state = _state(
            summaries=[
                _summary(title="A", path="x.md", tags=["python", "tooling"]),
                _summary(title="B", path="y.md", tags=["python"]),
            ]
        )
        result = await mcp_tools.list_by_tag(state, {"tags": ["python", "tooling"], "match": "all"})
        assert result["total"] == 1
        assert result["results"][0]["title"] == "A"

    @pytest.mark.asyncio
    async def test_empty_tag_list_short_circuits(self) -> None:
        state = _state(summaries=[_summary(title="A", path="x.md", tags=["python"])])
        result = await mcp_tools.list_by_tag(state, {"tags": []})
        assert result["total"] == 0
        assert result["results"] == []


class TestListTags:
    @pytest.mark.asyncio
    async def test_splits_into_primary_and_long_tail(self) -> None:
        state = _state(
            summaries=[_summary(title=str(i), path=f"x{i}.md", tags=["dominant"]) for i in range(5)]
            + [_summary(title="rare", path="r.md", tags=["sparse"])]
        )
        result = await mcp_tools.list_tags(state, {"threshold": 3})
        primary_tags = {entry["tag"] for entry in result["primary"]}
        long_tail_tags = {entry["tag"] for entry in result["long_tail"]}
        assert primary_tags == {"dominant"}
        assert long_tail_tags == {"sparse"}
        assert result["total_unique"] == 2

    @pytest.mark.asyncio
    async def test_frequency_descending_then_alphabetical(self) -> None:
        state = _state(
            summaries=[
                _summary(title="1", path="a.md", tags=["beta"]),
                _summary(title="2", path="b.md", tags=["alpha"]),
                _summary(title="3", path="c.md", tags=["alpha", "beta"]),
            ]
        )
        result = await mcp_tools.list_tags(state, {"threshold": 1})
        ordered = [e["tag"] for e in result["primary"]]
        # alpha and beta both have count 2 → alphabetical tiebreak.
        assert ordered == ["alpha", "beta"]


class TestBrowseEntity:
    @pytest.mark.asyncio
    async def test_returns_not_found_for_missing_entity(self, tmp_path: Path) -> None:
        from bsage.garden.vault import Vault

        vault = Vault(tmp_path)
        vault.ensure_dirs()
        state = SimpleNamespace(vault=vault, graph_store=None, index_reader=None)
        result = await mcp_tools.browse_entity(state, {"name": "Nonexistent"})
        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_returns_backlinks_from_stub_frontmatter(self, tmp_path: Path) -> None:
        from bsage.garden.vault import Vault
        from bsage.garden.writer import GardenWriter

        vault = Vault(tmp_path)
        vault.ensure_dirs()
        writer = GardenWriter(vault)
        mention = vault.root / "garden" / "seedling" / "mentioning.md"
        mention.parent.mkdir(parents=True, exist_ok=True)
        mention.write_text("body", encoding="utf-8")
        await writer.ensure_entity_stub("Vaultwarden", mention)

        state = SimpleNamespace(vault=vault, graph_store=None, index_reader=None)
        result = await mcp_tools.browse_entity(state, {"name": "Vaultwarden"})
        assert result["found"] is True
        assert result["auto_stub"] is True
        assert "garden/seedling/mentioning.md" in result["backlinks"]


class TestBrowseCommunities:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_graph_store(self) -> None:
        state = SimpleNamespace(graph_store=None)
        result = await mcp_tools.browse_communities(state, {})
        assert result == {"communities": [], "total": 0}

    @pytest.mark.asyncio
    async def test_summarises_louvain_output(self) -> None:
        # Provide a graph_store that returns a tiny synthetic graph with
        # two clearly separated communities.
        import networkx as nx

        graph = nx.MultiDiGraph()
        for n in ("a1", "a2", "a3"):
            graph.add_node(n, source_path=f"x/{n}.md")
        for n in ("b1", "b2", "b3"):
            graph.add_node(n, source_path=f"y/{n}.md")
        for u, v in (("a1", "a2"), ("a2", "a3"), ("a3", "a1")):
            graph.add_edge(u, v)
        for u, v in (("b1", "b2"), ("b2", "b3"), ("b3", "b1")):
            graph.add_edge(u, v)

        graph_store = MagicMock()
        graph_store.snapshot = AsyncMock(return_value=graph)
        state = SimpleNamespace(graph_store=graph_store)

        result = await mcp_tools.browse_communities(state, {"min_size": 2})
        assert result["total"] >= 2
        for c in result["communities"]:
            assert {"id", "label", "size", "cohesion"}.issubset(c.keys())
