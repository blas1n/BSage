"""Tests for the maturity-promoter plugin."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def _make_context(
    garden_root: Path,
    rel_count: int = 0,
    source_count: int = 0,
    updated_at: str | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.garden = AsyncMock()
    ctx.garden.promote_maturity = AsyncMock(
        return_value={"promoted": 0, "checked": 0, "details": []}
    )
    ctx.garden.write_action = AsyncMock()
    ctx.graph = AsyncMock()
    ctx.graph.count_relationships_for_entity = AsyncMock(return_value=rel_count)
    ctx.graph.count_distinct_sources = AsyncMock(return_value=source_count)
    ctx.graph.get_entity_updated_at = AsyncMock(return_value=updated_at)
    return ctx


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "maturity_promoter", "plugins/maturity-promoter/plugin.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


class TestMaturityPromoterPlugin:
    """Test maturity-promoter plugin execution."""

    async def test_execute_calls_promote_maturity(self, tmp_path: Path) -> None:
        execute = _load_plugin()
        ctx = _make_context(tmp_path)
        result = await execute(ctx)
        ctx.garden.promote_maturity.assert_called_once_with(ctx.graph)
        assert result["promoted"] == 0

    async def test_execute_logs_action_when_promoted(self, tmp_path: Path) -> None:
        execute = _load_plugin()
        ctx = _make_context(tmp_path)
        ctx.garden.promote_maturity = AsyncMock(
            return_value={
                "promoted": 2,
                "checked": 10,
                "details": [
                    {"path": "garden/idea/a.md", "from": "seed", "to": "seedling"},
                    {"path": "garden/idea/b.md", "from": "seedling", "to": "budding"},
                ],
            }
        )
        result = await execute(ctx)
        assert result["promoted"] == 2
        ctx.garden.write_action.assert_called_once()
        call_args = ctx.garden.write_action.call_args
        assert call_args[0][0] == "maturity-promoter"
        assert "2 notes" in call_args[0][1]

    async def test_execute_skips_action_when_no_promotion(self, tmp_path: Path) -> None:
        execute = _load_plugin()
        ctx = _make_context(tmp_path)
        await execute(ctx)
        ctx.garden.write_action.assert_not_called()

    async def test_plugin_metadata(self) -> None:
        execute = _load_plugin()
        meta = execute.__plugin__
        assert meta["name"] == "maturity-promoter"
        assert meta["category"] == "process"
        assert meta["trigger"]["type"] == "cron"
