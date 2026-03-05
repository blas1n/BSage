"""Tests for bsage.garden.sync — SyncManager and WriteEvent."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from bsage.core.skill_loader import SkillMeta
from bsage.garden.sync import (
    PluginSyncAdapter,
    SyncBackend,
    SyncManager,
    WriteEvent,
    WriteEventType,
)


def _make_event(
    event_type: WriteEventType = WriteEventType.SEED,
    path: str = "/vault/seeds/test/2026-02-22.md",
    source: str = "test-skill",
) -> WriteEvent:
    return WriteEvent(event_type=event_type, path=Path(path), source=source)


def _make_backend(
    name: str = "test-backend",
    sync_side_effect: Exception | None = None,
) -> AsyncMock:
    backend = AsyncMock(spec=SyncBackend)
    type(backend).name = PropertyMock(return_value=name)
    if sync_side_effect:
        backend.sync.side_effect = sync_side_effect
    return backend


class TestWriteEvent:
    """Test WriteEvent dataclass."""

    def test_write_event_fields(self) -> None:
        event = _make_event()
        assert event.event_type == WriteEventType.SEED
        assert event.path == Path("/vault/seeds/test/2026-02-22.md")
        assert event.source == "test-skill"

    def test_write_event_types(self) -> None:
        assert WriteEventType.SEED.value == "seed"
        assert WriteEventType.GARDEN.value == "garden"
        assert WriteEventType.ACTION.value == "action"


class TestSyncManagerRegistration:
    """Test register/unregister/list_backends."""

    def test_register_adds_backend(self) -> None:
        mgr = SyncManager()
        backend = _make_backend("s3")
        mgr.register(backend)
        assert mgr.list_backends() == ["s3"]

    def test_register_multiple_backends(self) -> None:
        mgr = SyncManager()
        mgr.register(_make_backend("s3"))
        mgr.register(_make_backend("git"))
        assert set(mgr.list_backends()) == {"s3", "git"}

    def test_unregister_removes_backend(self) -> None:
        mgr = SyncManager()
        mgr.register(_make_backend("s3"))
        mgr.unregister("s3")
        assert mgr.list_backends() == []

    def test_unregister_unknown_raises(self) -> None:
        mgr = SyncManager()
        with pytest.raises(KeyError):
            mgr.unregister("nonexistent")

    def test_list_backends_empty(self) -> None:
        mgr = SyncManager()
        assert mgr.list_backends() == []

    def test_register_replaces_existing(self) -> None:
        mgr = SyncManager()
        mgr.register(_make_backend("s3"))
        new_backend = _make_backend("s3")
        mgr.register(new_backend)
        assert mgr.list_backends() == ["s3"]


class TestSyncManagerNotify:
    """Test notify dispatches to backends."""

    async def test_notify_calls_sync(self) -> None:
        mgr = SyncManager()
        backend = _make_backend("s3")
        mgr.register(backend)

        event = _make_event()
        await mgr.notify(event)
        backend.sync.assert_called_once_with(event)

    async def test_notify_calls_all_backends(self) -> None:
        mgr = SyncManager()
        b1 = _make_backend("s3")
        b2 = _make_backend("git")
        mgr.register(b1)
        mgr.register(b2)

        event = _make_event()
        await mgr.notify(event)
        b1.sync.assert_called_once_with(event)
        b2.sync.assert_called_once_with(event)

    async def test_notify_no_backends(self) -> None:
        mgr = SyncManager()
        event = _make_event()
        # Should not raise
        await mgr.notify(event)

    async def test_notify_failure_does_not_propagate(self) -> None:
        mgr = SyncManager()
        failing = _make_backend("broken", sync_side_effect=RuntimeError("network error"))
        mgr.register(failing)

        event = _make_event()
        # Should not raise
        await mgr.notify(event)
        failing.sync.assert_called_once()

    async def test_notify_one_failure_does_not_block_others(self) -> None:
        mgr = SyncManager()
        failing = _make_backend("broken", sync_side_effect=RuntimeError("fail"))
        healthy = _make_backend("healthy")
        mgr.register(failing)
        mgr.register(healthy)

        event = _make_event()
        await mgr.notify(event)
        # Both should be called
        failing.sync.assert_called_once()
        healthy.sync.assert_called_once()


def _make_skill_meta(name: str) -> SkillMeta:
    return SkillMeta(
        name=name,
        version="1.0.0",
        category="output",
        description=f"Test output skill {name}",
    )


class TestSyncManagerOutputSkills:
    """Test output skill execution on write events."""

    async def test_output_skill_executed_on_notify(self) -> None:
        mgr = SyncManager()
        meta = _make_skill_meta("s3-output")
        runner = MagicMock()
        runner.run = AsyncMock(return_value={"status": "ok"})
        ctx = MagicMock()
        builder = MagicMock(return_value=ctx)

        mgr.register_output_skills([meta], runner, builder)

        event = _make_event()
        await mgr.notify(event)

        builder.assert_called_once()
        call_kwargs = builder.call_args
        assert "event_type" in call_kwargs.kwargs.get(
            "input_data", call_kwargs.args[0] if call_kwargs.args else {}
        )
        runner.run.assert_called_once_with(meta, ctx)

    async def test_output_skill_failure_does_not_propagate(self) -> None:
        mgr = SyncManager()
        meta = _make_skill_meta("broken-output")
        runner = MagicMock()
        runner.run = AsyncMock(side_effect=RuntimeError("fail"))
        builder = MagicMock(return_value=MagicMock())

        mgr.register_output_skills([meta], runner, builder)

        event = _make_event()
        await mgr.notify(event)  # Should not raise

    async def test_no_output_skills_is_noop(self) -> None:
        mgr = SyncManager()
        event = _make_event()
        await mgr.notify(event)  # No output skills registered, should not raise

    def test_register_warns_on_non_output_category(self) -> None:
        mgr = SyncManager()
        process_meta = SkillMeta(
            name="wrong-category",
            version="1.0.0",
            category="process",
            description="Not an output skill",
        )
        runner = MagicMock()
        builder = MagicMock()

        with patch("bsage.garden.sync.logger") as mock_logger:
            mgr.register_output_skills([process_meta], runner, builder)
            mock_logger.warning.assert_called_once()
            call_kwargs = mock_logger.warning.call_args
            assert call_kwargs.args[0] == "non_output_skill_rejected"

        # Rejected — not registered
        assert len(mgr._output_skills) == 0


class TestPluginSyncAdapter:
    """Test PluginSyncAdapter wraps output plugins as SyncBackend."""

    def test_adapter_name_from_meta(self) -> None:
        meta = MagicMock()
        meta.name = "local-output"
        meta.category = "output"
        adapter = PluginSyncAdapter(meta, MagicMock(), MagicMock())
        assert adapter.name == "local-output"

    async def test_adapter_sync_calls_runner(self) -> None:
        meta = MagicMock()
        meta.name = "git-output"
        runner = MagicMock()
        runner.run = AsyncMock(return_value={"ok": True})
        ctx = MagicMock()
        builder = MagicMock(return_value=ctx)

        adapter = PluginSyncAdapter(meta, runner, builder)
        event = _make_event(source="test-plugin")
        await adapter.sync(event)

        builder.assert_called_once()
        runner.run.assert_called_once_with(meta, ctx)

    async def test_adapter_passes_event_data(self) -> None:
        meta = MagicMock()
        meta.name = "s3-output"
        runner = MagicMock()
        runner.run = AsyncMock()
        builder = MagicMock(return_value=MagicMock())

        adapter = PluginSyncAdapter(meta, runner, builder)
        event = _make_event(
            event_type=WriteEventType.GARDEN,
            path="/vault/garden/idea/test.md",
            source="weekly-digest",
        )
        await adapter.sync(event)

        call_kwargs = builder.call_args.kwargs
        assert call_kwargs["input_data"]["event_type"] == "garden"
        assert call_kwargs["input_data"]["source"] == "weekly-digest"


class TestSyncManagerOutputPlugins:
    """Test register_output_plugins wraps plugins as adapters."""

    def test_register_output_plugins_adds_backends(self) -> None:
        mgr = SyncManager()
        meta1 = MagicMock()
        meta1.name = "local-output"
        meta1.category = "output"
        meta2 = MagicMock()
        meta2.name = "git-output"
        meta2.category = "output"

        mgr.register_output_plugins([meta1, meta2], MagicMock(), MagicMock())
        assert set(mgr.list_backends()) == {"local-output", "git-output"}

    def test_register_output_plugins_rejects_non_output(self) -> None:
        mgr = SyncManager()
        meta = MagicMock()
        meta.name = "process-thing"
        meta.category = "process"

        mgr.register_output_plugins([meta], MagicMock(), MagicMock())
        assert mgr.list_backends() == []

    async def test_registered_output_plugin_called_on_notify(self) -> None:
        mgr = SyncManager()
        meta = MagicMock()
        meta.name = "local-output"
        meta.category = "output"
        runner = MagicMock()
        runner.run = AsyncMock(return_value={"synced": True})
        builder = MagicMock(return_value=MagicMock())

        mgr.register_output_plugins([meta], runner, builder)

        event = _make_event()
        await mgr.notify(event)

        runner.run.assert_called_once()


class TestSyncManagerEnabledFiltering:
    """Test that notify() skips backends/skills not in enabled_entries."""

    def _make_runtime_config(self, enabled: set[str]) -> MagicMock:
        rc = MagicMock()
        type(rc).enabled_entries = PropertyMock(return_value=enabled)
        return rc

    async def test_notify_skips_disabled_backend(self) -> None:
        rc = self._make_runtime_config({"other-output"})
        mgr = SyncManager(runtime_config=rc)
        backend = _make_backend("notion-output")
        mgr.register(backend)

        await mgr.notify(_make_event())
        backend.sync.assert_not_called()

    async def test_notify_runs_enabled_backend(self) -> None:
        rc = self._make_runtime_config({"s3-output"})
        mgr = SyncManager(runtime_config=rc)
        backend = _make_backend("s3-output")
        mgr.register(backend)

        event = _make_event()
        await mgr.notify(event)
        backend.sync.assert_called_once_with(event)

    async def test_notify_skips_disabled_output_skill(self) -> None:
        rc = self._make_runtime_config(set())
        mgr = SyncManager(runtime_config=rc)
        meta = _make_skill_meta("notion-output")
        runner = MagicMock()
        runner.run = AsyncMock()
        builder = MagicMock(return_value=MagicMock())
        mgr.register_output_skills([meta], runner, builder)

        await mgr.notify(_make_event())
        runner.run.assert_not_called()

    async def test_notify_runs_enabled_output_skill(self) -> None:
        rc = self._make_runtime_config({"s3-output"})
        mgr = SyncManager(runtime_config=rc)
        meta = _make_skill_meta("s3-output")
        runner = MagicMock()
        runner.run = AsyncMock(return_value={"ok": True})
        ctx = MagicMock()
        builder = MagicMock(return_value=ctx)
        mgr.register_output_skills([meta], runner, builder)

        await mgr.notify(_make_event())
        runner.run.assert_called_once_with(meta, ctx)

    async def test_no_runtime_config_runs_all(self) -> None:
        mgr = SyncManager()  # no runtime_config
        backend = _make_backend("s3-output")
        mgr.register(backend)

        event = _make_event()
        await mgr.notify(event)
        backend.sync.assert_called_once_with(event)


class TestSyncBackendProtocol:
    """Test that SyncBackend is a runtime-checkable protocol."""

    def test_mock_implements_protocol(self) -> None:
        backend = _make_backend("test")
        assert isinstance(backend, SyncBackend)
