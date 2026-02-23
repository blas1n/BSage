"""Tests for bsage.core.scheduler — trigger registration and cron scheduling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillMeta


def _make_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "input",
        "is_dangerous": False,
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
        "calendar-input": _make_meta(
            name="calendar-input",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
        ),
        "weekly-digest": _make_meta(
            name="weekly-digest",
            category="process",
            trigger={"type": "cron", "schedule": "0 9 * * 1"},
        ),
    }
    loop.get_skill = MagicMock(side_effect=lambda name: registry[name])
    loop.build_context = MagicMock(return_value=MagicMock())
    return loop


@pytest.fixture()
def mock_skill_runner():
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
    """Test trigger registration from skill registry."""

    def test_register_input_cron_trigger(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "calendar-input": _make_meta(
                name="calendar-input",
                trigger={"type": "cron", "schedule": "*/15 * * * *"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "calendar-input" in scheduler._jobs

    def test_register_process_cron_trigger(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "weekly-digest": _make_meta(
                name="weekly-digest",
                category="process",
                trigger={"type": "cron", "schedule": "0 9 * * 1"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "weekly-digest" in scheduler._jobs

    def test_register_both_input_and_process(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "calendar-input": _make_meta(
                name="calendar-input",
                trigger={"type": "cron", "schedule": "*/15 * * * *"},
            ),
            "weekly-digest": _make_meta(
                name="weekly-digest",
                category="process",
                trigger={"type": "cron", "schedule": "0 9 * * 1"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "calendar-input" in scheduler._jobs
        assert "weekly-digest" in scheduler._jobs

    def test_register_skips_non_cron_trigger(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "webhook-skill": _make_meta(
                name="webhook-skill",
                trigger={"type": "webhook"},
            ),
        }
        scheduler.register_triggers(registry)
        assert "webhook-skill" not in scheduler._jobs

    def test_register_skips_no_trigger(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "process-skill": _make_meta(
                name="process-skill",
                category="process",
                trigger=None,
            ),
        }
        scheduler.register_triggers(registry)
        assert len(scheduler._jobs) == 0

    def test_register_skips_output_cron(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        registry = {
            "s3-output": _make_meta(
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
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        assert scheduler._scheduler.running is True
        scheduler.stop()

    async def test_stop_stops_apscheduler(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        scheduler.start()
        scheduler.stop()
        # AsyncIOScheduler defers state change to event loop
        await asyncio.sleep(0)
        assert scheduler._scheduler.running is False

    def test_stop_without_start_is_safe(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        # Should not raise
        scheduler.stop()


class TestSchedulerInputTrigger:
    """Test input trigger execution."""

    async def test_input_trigger_runs_skill_and_feeds_agent_loop(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_input_trigger("calendar-input")

        mock_skill_runner.run.assert_called_once()
        mock_agent_loop.on_input.assert_called_once_with("calendar-input", {"events": [1, 2]})

    async def test_input_trigger_handles_skill_error(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        mock_skill_runner.run = AsyncMock(side_effect=RuntimeError("skill failed"))
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        # Should not raise — error is logged internally
        await scheduler._on_input_trigger("calendar-input")
        mock_agent_loop.on_input.assert_not_called()

    async def test_input_trigger_missing_skill(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        # Should not raise — KeyError is caught by exception handler
        await scheduler._on_input_trigger("nonexistent")
        mock_skill_runner.run.assert_not_called()


class TestSchedulerProcessTrigger:
    """Test process trigger execution."""

    async def test_process_trigger_runs_skill_and_writes_action(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("weekly-digest")

        mock_skill_runner.run.assert_called_once()
        mock_agent_loop.write_action.assert_called_once()
        # Process trigger should NOT call on_input
        mock_agent_loop.on_input.assert_not_called()

    async def test_process_trigger_handles_skill_error(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        mock_skill_runner.run = AsyncMock(side_effect=RuntimeError("fail"))
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        # Should not raise — error is logged internally
        await scheduler._on_process_trigger("weekly-digest")
        mock_agent_loop.write_action.assert_not_called()

    async def test_process_trigger_blocks_dangerous_skill(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        mock_safe_mode_guard.check = AsyncMock(return_value=False)
        registry = {
            "dangerous-process": _make_meta(
                name="dangerous-process",
                category="process",
                is_dangerous=True,
                trigger={"type": "cron", "schedule": "0 9 * * 1"},
            ),
        }
        mock_agent_loop.get_skill = MagicMock(side_effect=lambda name: registry[name])
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("dangerous-process")

        mock_safe_mode_guard.check.assert_called_once()
        mock_skill_runner.run.assert_not_called()
        mock_agent_loop.write_action.assert_not_called()

    async def test_process_trigger_passes_full_summary(
        self, mock_agent_loop, mock_skill_runner, mock_safe_mode_guard
    ) -> None:
        mock_skill_runner.run = AsyncMock(return_value={"data": "x" * 300})
        scheduler = Scheduler(
            agent_loop=mock_agent_loop,
            skill_runner=mock_skill_runner,
            safe_mode_guard=mock_safe_mode_guard,
        )
        await scheduler._on_process_trigger("weekly-digest")
        call_args = mock_agent_loop.write_action.call_args
        summary = call_args.args[1]
        # Truncation is now handled by GardenWriter.write_action internally
        assert "x" in summary
        assert call_args.args[0] == "weekly-digest"
