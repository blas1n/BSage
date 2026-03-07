"""Tests for bsage.core.scheduler — trigger registration and cron scheduling."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.plugin_loader import PluginMeta
from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillMeta


def _make_plugin_meta(**overrides) -> PluginMeta:
    defaults = {
        "name": "test-plugin",
        "version": "1.0.0",
        "category": "input",
        "description": "Test plugin",
    }
    defaults.update(overrides)
    return PluginMeta(**defaults)


def _make_skill_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "process",
        "description": "Test skill",
    }
    defaults.update(overrides)
    return SkillMeta(**defaults)


@pytest.fixture()
def mock_agent_loop():
    loop = MagicMock()
    loop.on_input = AsyncMock(return_value=[{"status": "ok"}])
    loop.write_action = AsyncMock()
    registry = {
        "calendar-input": _make_plugin_meta(
            name="calendar-input",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
        ),
        "weekly-digest": _make_skill_meta(
            name="weekly-digest",
            trigger={"type": "cron", "schedule": "0 9 * * 1"},
        ),
    }
    loop.get_entry = MagicMock(side_effect=lambda name: registry[name])
    loop.build_context = MagicMock(return_value=MagicMock())
    return loop


@pytest.fixture()
def mock_runner():
    runner = MagicMock()
    runner.run = AsyncMock(return_value={"events": [1, 2]})
    return runner


@pytest.fixture()
def mock_safe_mode_guard():
    guard = MagicMock()
    guard.check = AsyncMock(return_value=True)
    return guard


class TestParseCron:
    """Test cron expression parsing."""

    def test_parse_standard_cron(self) -> None:
        result = Scheduler._parse_cron("*/15 * * * *")
        assert result == {
            "minute": "*/15",
            "hour": "*",
            "day": "*",
            "month": "*",
            "day_of_week": "*",
        }

    def test_parse_specific_time(self) -> None:
        result = Scheduler._parse_cron("30 9 * * 1-5")
        assert result == {
            "minute": "30",
            "hour": "9",
            "day": "*",
            "month": "*",
            "day_of_week": "1-5",
        }

    def test_parse_invalid_cron_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid cron"):
            Scheduler._parse_cron("*/15 *")

    def test_parse_daily_midnight(self) -> None:
        result = Scheduler._parse_cron("0 0 * * *")
        assert result["minute"] == "0"
        assert result["hour"] == "0"


class TestSchedulerRegisterTriggers:
    """Test trigger registration from registry."""

    def test_register_input_cron_trigger(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "calendar-input": _make_plugin_meta(
                name="calendar-input",
                trigger={"type": "cron", "schedule": "*/15 * * * *"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "calendar-input" in scheduler._jobs

    def test_register_process_cron_trigger(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "weekly-digest": _make_skill_meta(
                name="weekly-digest",
                trigger={"type": "cron", "schedule": "0 9 * * 1"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "weekly-digest" in scheduler._jobs

    def test_register_both_input_and_process(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "calendar-input": _make_plugin_meta(
                name="calendar-input",
                trigger={"type": "cron", "schedule": "*/15 * * * *"},
            ),
            "weekly-digest": _make_skill_meta(
                name="weekly-digest",
                trigger={"type": "cron", "schedule": "0 9 * * 1"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "calendar-input" in scheduler._jobs
        assert "weekly-digest" in scheduler._jobs

    def test_register_skips_non_cron_trigger(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "webhook-plugin": _make_plugin_meta(
                name="webhook-plugin",
                trigger={"type": "webhook"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "webhook-plugin" not in scheduler._jobs

    def test_register_skips_no_trigger(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "process-skill": _make_skill_meta(
                name="process-skill",
                trigger=None,
            ),
        }
        scheduler.register_triggers(registry)
        assert len(scheduler._jobs) == 0

    def test_register_skips_output_cron(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "s3-output": _make_plugin_meta(
                name="s3-output",
                category="output",
                trigger={"type": "cron", "schedule": "0 * * * *"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "s3-output" not in scheduler._jobs


class TestSchedulerStartStop:
    """Test scheduler start and stop."""

    async def test_start_starts_apscheduler(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        assert scheduler._scheduler.running is True
        scheduler.stop()

    async def test_stop_stops_apscheduler(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        scheduler.stop()
        await asyncio.sleep(0)
        assert scheduler._scheduler.running is False

    def test_stop_without_start_is_safe(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.stop()


class TestSchedulerInputTrigger:
    """Test input trigger execution."""

    async def test_input_trigger_runs_entry_and_feeds_agent_loop(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_input_trigger("calendar-input")

        mock_runner.run.assert_called_once()
        mock_agent_loop.on_input.assert_called_once_with("calendar-input", {"events": [1, 2]})

    async def test_input_trigger_handles_error(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        mock_runner.run = AsyncMock(side_effect=RuntimeError("failed"))
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_input_trigger("calendar-input")
        mock_agent_loop.on_input.assert_not_called()

    async def test_input_trigger_missing_entry(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_input_trigger("nonexistent")
        mock_runner.run.assert_not_called()


class TestSchedulerProcessTrigger:
    """Test process trigger execution."""

    async def test_process_trigger_runs_entry_and_writes_action(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("weekly-digest")

        mock_runner.run.assert_called_once()
        mock_agent_loop.write_action.assert_called_once()
        mock_agent_loop.on_input.assert_not_called()

    async def test_process_trigger_handles_error(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        mock_runner.run = AsyncMock(side_effect=RuntimeError("fail"))
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("weekly-digest")
        mock_agent_loop.write_action.assert_not_called()

    async def test_process_trigger_blocks_dangerous_entry(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        mock_safe_mode_guard.check = AsyncMock(return_value=False)
        registry = {
            "dangerous-process": _make_skill_meta(
                name="dangerous-process",
                trigger={"type": "cron", "schedule": "0 9 * * 1"},
            ),
        }
        mock_agent_loop.get_entry = MagicMock(side_effect=lambda name: registry[name])
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("dangerous-process")

        mock_safe_mode_guard.check.assert_called_once()
        mock_runner.run.assert_not_called()
        mock_agent_loop.write_action.assert_not_called()


class TestSchedulerMissingCredentials:
    """Test graceful handling of MissingCredentialError."""

    async def test_input_trigger_skips_on_missing_credentials(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        from bsage.core.plugin_runner import MissingCredentialError

        mock_runner.run = AsyncMock(side_effect=MissingCredentialError("missing creds"))
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_input_trigger("calendar-input")

        mock_agent_loop.on_input.assert_not_called()

    async def test_process_trigger_skips_on_missing_credentials(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        from bsage.core.plugin_runner import MissingCredentialError

        mock_runner.run = AsyncMock(side_effect=MissingCredentialError("missing creds"))
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("weekly-digest")

        mock_agent_loop.write_action.assert_not_called()

    async def test_input_trigger_emits_credential_setup_required(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        from bsage.core.events import EventBus, EventType
        from bsage.core.plugin_runner import MissingCredentialError

        mock_runner.run = AsyncMock(side_effect=MissingCredentialError("missing creds"))
        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
            event_bus=event_bus,
        )
        await scheduler._on_input_trigger("calendar-input")

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(
            e.event_type == EventType.CREDENTIAL_SETUP_REQUIRED
            and e.payload["name"] == "calendar-input"
            for e in events
        )

    async def test_process_trigger_emits_credential_setup_required(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        from bsage.core.events import EventBus, EventType
        from bsage.core.plugin_runner import MissingCredentialError

        mock_runner.run = AsyncMock(side_effect=MissingCredentialError("missing creds"))
        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
            event_bus=event_bus,
        )
        await scheduler._on_process_trigger("weekly-digest")

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(
            e.event_type == EventType.CREDENTIAL_SETUP_REQUIRED
            and e.payload["name"] == "weekly-digest"
            for e in events
        )


class TestSchedulerEvents:
    """Test EventBus emission from Scheduler."""

    async def test_input_trigger_emits_trigger_fired(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
            event_bus=event_bus,
        )
        await scheduler._on_input_trigger("calendar-input")

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(
            e.event_type == EventType.TRIGGER_FIRED and e.payload["category"] == "input"
            for e in events
        )

    async def test_process_trigger_emits_trigger_fired(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
            event_bus=event_bus,
        )
        await scheduler._on_process_trigger("weekly-digest")

        events = [c.args[0] for c in sub.on_event.call_args_list]
        assert any(
            e.event_type == EventType.TRIGGER_FIRED and e.payload["category"] == "process"
            for e in events
        )

    async def test_no_events_when_event_bus_is_none(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        # Should not raise
        await scheduler._on_input_trigger("calendar-input")


class TestSchedulerPollingTrigger:
    """Test polling trigger registration and lifecycle."""

    async def test_register_polling_trigger_creates_task(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "telegram-input": _make_plugin_meta(
                name="telegram-input",
                trigger={"type": "polling"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "telegram-input" in scheduler._polling_tasks
        assert not scheduler._polling_tasks["telegram-input"].done()
        # Cleanup
        scheduler.stop()

    async def test_register_polling_does_not_create_cron_job(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "telegram-input": _make_plugin_meta(
                name="telegram-input",
                trigger={"type": "polling"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "telegram-input" not in scheduler._jobs
        scheduler.stop()

    async def test_stop_cancels_polling_tasks(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "telegram-input": _make_plugin_meta(
                name="telegram-input",
                trigger={"type": "polling"},
            ),
        }
        scheduler.register_triggers(registry)
        task = scheduler._polling_tasks["telegram-input"]
        scheduler.stop()
        await asyncio.sleep(0.05)
        assert task.cancelled() or task.done()
        assert len(scheduler._polling_tasks) == 0

    async def test_polling_loop_calls_on_input_trigger(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        call_count = 0
        original_on_input = mock_agent_loop.on_input

        async def counting_on_input(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError  # Stop after 2 iterations
            return await original_on_input(*args, **kwargs)

        mock_agent_loop.on_input = AsyncMock(side_effect=counting_on_input)

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        meta = _make_plugin_meta(
            name="calendar-input",
            trigger={"type": "polling"},
        )
        scheduler._register_polling("calendar-input", meta)
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(scheduler._polling_tasks["calendar-input"], timeout=2.0)

        assert call_count >= 1
        scheduler.stop()

    async def test_register_new_polling_trigger(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        new_entries = {
            "telegram-input": _make_plugin_meta(
                name="telegram-input",
                trigger={"type": "polling"},
            ),
        }
        scheduler.register_new_triggers(new_entries)
        assert "telegram-input" in scheduler._polling_tasks
        scheduler.stop()


class TestSchedulerAdapter:
    """Test SchedulerAdapter dynamic cron management."""

    async def test_add_cron_registers_job(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        await adapter.add_cron("my-job", "0 9 * * 1", "weekly-digest")
        assert "my-job" in scheduler._jobs
        assert scheduler._jobs["my-job"] == "bsage-dynamic-my-job"
        scheduler.stop()

    async def test_add_cron_persists_to_file(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        import json

        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        await adapter.add_cron("test-job", "*/5 * * * *", "some-target")
        assert persist_path.exists()
        data = json.loads(persist_path.read_text())
        assert any(e["name"] == "test-job" for e in data)
        scheduler.stop()

    async def test_add_cron_invalid_name_raises(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        with pytest.raises(ValueError, match="Invalid job name"):
            await adapter.add_cron("BAD NAME!", "0 9 * * 1", "target")

    async def test_add_cron_invalid_schedule_raises(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        with pytest.raises(ValueError, match="Invalid cron"):
            await adapter.add_cron("my-job", "bad schedule", "target")

    async def test_remove_cron_removes_job(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        await adapter.add_cron("remove-me", "0 0 * * *", "target")
        assert "remove-me" in scheduler._jobs

        await adapter.remove_cron("remove-me")
        assert "remove-me" not in scheduler._jobs
        scheduler.stop()

    async def test_remove_cron_nonexistent_raises(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        with pytest.raises(KeyError, match="No dynamic job"):
            await adapter.remove_cron("nonexistent")

    async def test_list_jobs_returns_registered_jobs(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        adapter = SchedulerAdapter(scheduler, persist_path)

        await adapter.add_cron("job-a", "0 0 * * *", "target-a")
        jobs = await adapter.list_jobs()
        assert len(jobs) >= 1
        assert any(j["name"] == "job-a" and j["dynamic"] is True for j in jobs)
        scheduler.stop()

    async def test_load_persisted_restores_jobs(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        import json

        from bsage.core.scheduler import SchedulerAdapter

        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        persist_path.parent.mkdir(parents=True)
        persist_path.write_text(
            json.dumps([{"name": "restored-job", "schedule": "0 6 * * *", "target": "my-target"}])
        )

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        adapter = SchedulerAdapter(scheduler, persist_path)
        await adapter.load_persisted()

        assert "restored-job" in scheduler._jobs
        scheduler.stop()

    async def test_load_persisted_handles_corrupt_json(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard, tmp_path
    ) -> None:
        from bsage.core.scheduler import SchedulerAdapter

        persist_path = tmp_path / ".scheduler" / "dynamic_jobs.json"
        persist_path.parent.mkdir(parents=True)
        persist_path.write_text("not valid json!!!")

        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        adapter = SchedulerAdapter(scheduler, persist_path)
        # Should not raise
        await adapter.load_persisted()
        assert len(scheduler._jobs) == 0

    async def test_register_new_polling_skips_existing(
        self, mock_agent_loop, mock_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            runner=mock_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        meta = _make_plugin_meta(
            name="telegram-input",
            trigger={"type": "polling"},
        )
        scheduler.register_triggers({"telegram-input": meta})
        first_task = scheduler._polling_tasks["telegram-input"]

        # Re-registering should not create a new task
        scheduler.register_new_triggers({"telegram-input": meta})
        assert scheduler._polling_tasks["telegram-input"] is first_task
        scheduler.stop()
