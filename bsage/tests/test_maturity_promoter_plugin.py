"""Tests for MaintenanceTasks (replaces maturity-promoter plugin)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.maintenance import MaintenanceTasks


def _make_writer():
    writer = MagicMock()
    writer.promote_maturity = AsyncMock(return_value={"promoted": 0, "checked": 0, "details": []})
    writer.write_action = AsyncMock()
    return writer


def _make_graph():
    graph = MagicMock()
    graph.count_relationships_for_entity = AsyncMock(return_value=0)
    graph.count_distinct_sources = AsyncMock(return_value=0)
    graph.get_entity_updated_at = AsyncMock(return_value=None)
    graph._fetchall = AsyncMock(return_value=[])
    graph._write_lock = MagicMock()
    graph._conn = MagicMock()
    return graph


class TestMaintenanceMaturity:
    @pytest.mark.asyncio()
    async def test_run_maturity_calls_promote(self):
        writer = _make_writer()
        tasks = MaintenanceTasks(garden_writer=writer, graph_store=MagicMock())
        result = await tasks.run_maturity()
        writer.promote_maturity.assert_called_once()
        assert result["promoted"] == 0

    @pytest.mark.asyncio()
    async def test_run_maturity_logs_action_on_promotion(self):
        writer = _make_writer()
        writer.promote_maturity = AsyncMock(
            return_value={
                "promoted": 2,
                "checked": 10,
                "details": [
                    {"path": "ideas/a.md", "from": "seed", "to": "seedling"},
                    {"path": "ideas/b.md", "from": "seedling", "to": "budding"},
                ],
            }
        )
        tasks = MaintenanceTasks(garden_writer=writer)
        result = await tasks.run_maturity()
        assert result["promoted"] == 2
        writer.write_action.assert_called_once()
        call_args = writer.write_action.call_args
        assert call_args[0][0] == "maintenance:maturity"
        assert "2 notes" in call_args[0][1]


class TestMaintenanceEdgeLifecycle:
    @pytest.mark.asyncio()
    async def test_run_edge_lifecycle_skips_without_graph(self):
        writer = _make_writer()
        tasks = MaintenanceTasks(garden_writer=writer, graph_store=None)
        result = await tasks.run_edge_lifecycle()
        assert result["status"] == "skipped"


class TestMaintenanceOntologyEvolution:
    @pytest.mark.asyncio()
    async def test_run_ontology_evolution_skips_without_deps(self):
        writer = _make_writer()
        tasks = MaintenanceTasks(garden_writer=writer)
        result = await tasks.run_ontology_evolution()
        assert result["status"] == "skipped"
