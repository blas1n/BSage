"""Tests for bsage.core.maintenance — built-in maintenance tasks."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.maintenance import MaintenanceTasks


@pytest.fixture()
def mock_settings():
    s = MagicMock()
    s.maturity_seedling_min_relationships = 2
    s.maturity_budding_min_sources = 3
    s.maturity_evergreen_min_days_stable = 14
    s.maturity_evergreen_min_relationships = 5
    s.edge_promotion_min_mentions = 3
    s.edge_decay_days = 90
    return s


@pytest.fixture()
def mock_garden():
    garden = AsyncMock()
    garden.promote_maturity = AsyncMock(return_value={"promoted": 0, "checked": 5, "details": []})
    garden.write_action = AsyncMock()
    return garden


@pytest.fixture()
def mock_graph():
    """Mock graph store with public API for EdgeLifecycleEvaluator."""
    g = AsyncMock()
    g.query = AsyncMock(return_value=[])
    g.execute_batch = AsyncMock(return_value=0)
    return g


@pytest.fixture()
def mock_ontology():
    return MagicMock()


class TestRunMaturity:
    async def test_calls_promote_maturity_with_settings_config(
        self, mock_garden, mock_graph, mock_settings
    ) -> None:
        tasks = MaintenanceTasks(
            garden_writer=mock_garden,
            graph_store=mock_graph,
            settings=mock_settings,
        )
        result = await tasks.run_maturity()
        assert result["checked"] == 5
        assert result["promoted"] == 0
        mock_garden.promote_maturity.assert_awaited_once()
        call_kwargs = mock_garden.promote_maturity.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config is not None
        assert config.seedling_min_relationships == 2

    async def test_writes_action_on_promotion(self, mock_garden, mock_graph) -> None:
        mock_garden.promote_maturity.return_value = {
            "promoted": 1,
            "checked": 3,
            "details": [{"path": "ideas/note.md", "from": "seed", "to": "seedling"}],
        }
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph)
        result = await tasks.run_maturity()
        assert result["promoted"] == 1
        mock_garden.write_action.assert_awaited_once()

    async def test_no_action_when_nothing_promoted(self, mock_garden, mock_graph) -> None:
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph)
        await tasks.run_maturity()
        mock_garden.write_action.assert_not_awaited()

    async def test_returns_error_dict_on_exception(self, mock_garden, mock_graph) -> None:
        mock_garden.promote_maturity.side_effect = RuntimeError("db error")
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph)
        result = await tasks.run_maturity()
        assert result["error"] is True
        assert result["promoted"] == 0

    async def test_uses_default_config_without_settings(self, mock_garden, mock_graph) -> None:
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph)
        await tasks.run_maturity()
        call_kwargs = mock_garden.promote_maturity.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config is None


class TestRunEdgeLifecycle:
    async def test_skips_without_graph(self, mock_garden) -> None:
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=None)
        result = await tasks.run_edge_lifecycle()
        assert result["status"] == "skipped"

    async def test_runs_with_settings(self, mock_garden, mock_graph, mock_settings) -> None:
        tasks = MaintenanceTasks(
            garden_writer=mock_garden,
            graph_store=mock_graph,
            settings=mock_settings,
        )
        result = await tasks.run_edge_lifecycle()
        assert "promoted" in result
        assert "demoted" in result

    async def test_runs_without_settings(self, mock_garden, mock_graph) -> None:
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph)
        result = await tasks.run_edge_lifecycle()
        assert "promoted" in result
        assert "demoted" in result

    async def test_returns_error_dict_on_exception(self, mock_garden, mock_graph) -> None:
        mock_graph.query = AsyncMock(side_effect=RuntimeError("db fail"))
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph)
        result = await tasks.run_edge_lifecycle()
        assert result["error"] is True


class TestRunOntologyEvolution:
    async def test_skips_without_ontology(self, mock_garden, mock_graph) -> None:
        tasks = MaintenanceTasks(garden_writer=mock_garden, graph_store=mock_graph, ontology=None)
        result = await tasks.run_ontology_evolution()
        assert result["status"] == "skipped"

    async def test_skips_without_graph(self, mock_garden, mock_ontology) -> None:
        tasks = MaintenanceTasks(
            garden_writer=mock_garden, graph_store=None, ontology=mock_ontology
        )
        result = await tasks.run_ontology_evolution()
        assert result["status"] == "skipped"

    async def test_returns_zero_counts_after_dynamic_ontology_refactor(
        self, mock_garden, mock_graph, mock_ontology
    ) -> None:
        """Entity-type evolution is a no-op now: types are free-form, so
        there's nothing to deprecate. The endpoint stays for schedule
        compatibility but always reports 0 candidates."""
        tasks = MaintenanceTasks(
            garden_writer=mock_garden,
            graph_store=mock_graph,
            ontology=mock_ontology,
        )
        result = await tasks.run_ontology_evolution()
        assert result["candidates"] == 0
        assert result["deprecated"] == 0
        assert "error" not in result
