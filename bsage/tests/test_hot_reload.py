"""Tests for hot-reload: scan_new() on loaders, register_new_triggers, on_refresh callback."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.agent_loop import AgentLoop
from bsage.core.plugin_loader import PluginLoader, PluginMeta
from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLUGIN_TEMPLATE = """\
from bsage.plugin import plugin

@plugin(
    name="{name}",
    version="1.0.0",
    category="{category}",
    description="Auto-generated test plugin",
{extra})
async def execute(context):
    return {{"ok": True}}
"""


def _write_plugin(plugins_dir, name, category="input", extra=""):
    d = plugins_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.py").write_text(_PLUGIN_TEMPLATE.format(name=name, category=category, extra=extra))
    return d


def _write_skill(skills_dir, name, category="process"):
    (skills_dir / f"{name}.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"version: 1.0.0\n"
        f"category: {category}\n"
        f"description: Auto-generated test skill\n"
        f"---\n\n"
        f"System prompt for {name}.\n"
    )


# ---------------------------------------------------------------------------
# PluginLoader.scan_new
# ---------------------------------------------------------------------------


class TestPluginLoaderScanNew:
    """Tests for PluginLoader.scan_new()."""

    async def test_finds_new_plugin(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _write_plugin(plugins_dir, "existing-plugin")

        loader = PluginLoader(plugins_dir)
        await loader.load_all()
        assert "existing-plugin" in loader._registry

        # Add a new plugin after initial load
        _write_plugin(plugins_dir, "new-plugin")
        new = await loader.scan_new()

        assert "new-plugin" in new
        assert "existing-plugin" not in new
        # Both should be in the registry now
        assert "existing-plugin" in loader._registry
        assert "new-plugin" in loader._registry

    async def test_skips_existing(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _write_plugin(plugins_dir, "only-plugin")

        loader = PluginLoader(plugins_dir)
        await loader.load_all()

        new = await loader.scan_new()
        assert new == {}

    async def test_nonexistent_dir_returns_empty(self, tmp_path) -> None:
        loader = PluginLoader(tmp_path / "does-not-exist")
        new = await loader.scan_new()
        assert new == {}

    async def test_danger_analyzer_called_for_new_only(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _write_plugin(plugins_dir, "old-plugin")

        analyzer = MagicMock()
        analyzer.analyze = AsyncMock(return_value=(False, "safe"))

        loader = PluginLoader(plugins_dir, danger_analyzer=analyzer)
        await loader.load_all()
        initial_call_count = analyzer.analyze.call_count

        # Add new plugin and scan
        _write_plugin(plugins_dir, "brand-new")
        await loader.scan_new()

        # DangerAnalyzer should have been called once more (for brand-new only)
        assert analyzer.analyze.call_count == initial_call_count + 1
        last_call_args = analyzer.analyze.call_args[0]
        assert last_call_args[0] == "brand-new"

    async def test_handles_load_failure_gracefully(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # Create a broken plugin (no @plugin decorator)
        d = plugins_dir / "broken"
        d.mkdir()
        (d / "plugin.py").write_text("def execute(): pass\n")

        loader = PluginLoader(plugins_dir)
        new = await loader.scan_new()
        assert "broken" not in new


# ---------------------------------------------------------------------------
# SkillLoader.scan_new
# ---------------------------------------------------------------------------


class TestSkillLoaderScanNew:
    """Tests for SkillLoader.scan_new()."""

    async def test_finds_new_skill(self, tmp_path) -> None:
        _write_skill(tmp_path, "existing-skill")

        loader = SkillLoader(tmp_path)
        await loader.load_all()
        assert "existing-skill" in loader._registry

        # Add a new skill after initial load
        _write_skill(tmp_path, "new-skill")
        new = await loader.scan_new()

        assert "new-skill" in new
        assert "existing-skill" not in new
        assert "existing-skill" in loader._registry
        assert "new-skill" in loader._registry

    async def test_skips_existing(self, tmp_path) -> None:
        _write_skill(tmp_path, "only-skill")

        loader = SkillLoader(tmp_path)
        await loader.load_all()

        new = await loader.scan_new()
        assert new == {}

    async def test_nonexistent_dir_returns_empty(self, tmp_path) -> None:
        loader = SkillLoader(tmp_path / "does-not-exist")
        new = await loader.scan_new()
        assert new == {}

    async def test_handles_invalid_skill_gracefully(self, tmp_path) -> None:
        _write_skill(tmp_path, "good-skill")

        loader = SkillLoader(tmp_path)
        await loader.load_all()

        # Add a broken skill (missing required fields)
        (tmp_path / "broken.md").write_text("---\nname: broken\n---\nBody\n")
        new = await loader.scan_new()
        assert "broken" not in new
        assert "good-skill" in loader._registry

    async def test_new_skill_has_system_prompt(self, tmp_path) -> None:
        loader = SkillLoader(tmp_path)

        _write_skill(tmp_path, "fresh-skill")
        new = await loader.scan_new()

        meta = new["fresh-skill"]
        assert meta.system_prompt == "System prompt for fresh-skill."


# ---------------------------------------------------------------------------
# Scheduler.register_new_triggers
# ---------------------------------------------------------------------------


class TestSchedulerRegisterNewTriggers:
    """Tests for Scheduler.register_new_triggers()."""

    @pytest.fixture()
    def scheduler(self) -> Scheduler:
        agent_loop = MagicMock()
        runner = MagicMock()
        safe_mode_guard = MagicMock()
        s = Scheduler(
            agent_loop=agent_loop,
            runner=runner,
            safe_mode_guard=safe_mode_guard,
        )
        return s

    def test_registers_new_cron_trigger(self, scheduler) -> None:
        meta = PluginMeta(
            name="cron-plugin",
            version="1.0.0",
            category="input",
            description="Cron test",
            trigger={"type": "cron", "schedule": "0 * * * *"},
        )
        scheduler.register_new_triggers({"cron-plugin": meta})
        assert "cron-plugin" in scheduler._jobs

    def test_skips_already_registered(self, scheduler) -> None:
        meta = PluginMeta(
            name="existing",
            version="1.0.0",
            category="input",
            description="Already there",
            trigger={"type": "cron", "schedule": "0 * * * *"},
        )
        # Register once via normal path
        scheduler.register_triggers({"existing": meta})
        job_id = scheduler._jobs["existing"]

        # Try to register again via register_new_triggers
        scheduler.register_new_triggers({"existing": meta})
        # Job ID should be unchanged (not re-registered)
        assert scheduler._jobs["existing"] == job_id

    def test_skips_non_cron_triggers(self, scheduler) -> None:
        meta = PluginMeta(
            name="webhook-plugin",
            version="1.0.0",
            category="input",
            description="Webhook",
            trigger={"type": "webhook"},
        )
        scheduler.register_new_triggers({"webhook-plugin": meta})
        assert "webhook-plugin" not in scheduler._jobs

    def test_skips_output_category(self, scheduler) -> None:
        meta = PluginMeta(
            name="output-cron",
            version="1.0.0",
            category="output",
            description="Output with cron",
            trigger={"type": "cron", "schedule": "0 * * * *"},
        )
        scheduler.register_new_triggers({"output-cron": meta})
        assert "output-cron" not in scheduler._jobs


# ---------------------------------------------------------------------------
# AgentLoop on_refresh callback
# ---------------------------------------------------------------------------


class TestAgentLoopOnRefresh:
    """Tests for AgentLoop calling the on_refresh callback."""

    @pytest.fixture()
    def mock_deps(self):
        registry = {}
        runner = MagicMock()
        runner.run = AsyncMock(return_value={"status": "ok"})
        safe_mode_guard = MagicMock()
        safe_mode_guard.check = AsyncMock(return_value=True)
        garden_writer = MagicMock()
        garden_writer.write_seed = AsyncMock()
        garden_writer.write_action = AsyncMock()
        garden_writer.write_input_log = AsyncMock()
        llm_client = MagicMock()
        llm_client.chat = AsyncMock(return_value="none")
        return {
            "registry": registry,
            "runner": runner,
            "safe_mode_guard": safe_mode_guard,
            "garden_writer": garden_writer,
            "llm_client": llm_client,
        }

    async def test_on_input_calls_refresh(self, mock_deps) -> None:
        refresh = AsyncMock()
        loop = AgentLoop(**mock_deps, on_refresh=refresh)
        await loop.on_input("test-plugin", {"data": 1})
        refresh.assert_awaited_once()

    async def test_chat_calls_refresh(self, mock_deps) -> None:
        refresh = AsyncMock()
        loop = AgentLoop(**mock_deps, on_refresh=refresh)
        await loop.chat("system", [{"role": "user", "content": "hi"}])
        refresh.assert_awaited_once()

    async def test_no_refresh_callback_ok(self, mock_deps) -> None:
        loop = AgentLoop(**mock_deps)
        # Should not raise when on_refresh is None
        await loop.on_input("test-plugin", {"data": 1})

    async def test_refresh_called_before_processing(self, mock_deps) -> None:
        """Verify refresh is called before the main logic (write_seed)."""
        call_order = []

        async def track_refresh():
            call_order.append("refresh")

        async def track_write_seed(*args, **kwargs):
            call_order.append("write_seed")

        mock_deps["garden_writer"].write_seed = track_write_seed
        loop = AgentLoop(**mock_deps, on_refresh=track_refresh)
        await loop.on_input("test-plugin", {"data": 1})

        assert call_order[0] == "refresh"
        assert call_order[1] == "write_seed"
