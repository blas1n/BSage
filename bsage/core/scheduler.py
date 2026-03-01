"""Scheduler — registers cron triggers for input and process plugins/skills via APScheduler."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bsage.core.events import emit_event

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.core.protocols import SchedulerSupport
    from bsage.core.runner import Runner
    from bsage.core.safe_mode import SafeModeGuard

logger = structlog.get_logger(__name__)

_CRON_FIELDS = ("minute", "hour", "day", "month", "day_of_week")


class Scheduler:
    """Registers and manages cron triggers for input and process plugins/skills."""

    def __init__(
        self,
        agent_loop: SchedulerSupport,
        runner: Runner,
        safe_mode_guard: SafeModeGuard,
        event_bus: EventBus | None = None,
    ) -> None:
        self._agent_loop = agent_loop
        self._runner = runner
        self._safe_mode_guard = safe_mode_guard
        self._event_bus = event_bus
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # name -> job_id

    def register_triggers(self, registry: dict[str, Any]) -> None:
        """Register cron triggers for input and process plugins/skills."""
        for name, meta in registry.items():
            if not meta.trigger or meta.trigger.get("type") != "cron":
                continue

            if meta.category == "input":
                callback = self._on_input_trigger
            elif meta.category == "process":
                callback = self._on_process_trigger
            else:
                continue

            schedule = meta.trigger.get("schedule", "")
            try:
                cron_kwargs = self._parse_cron(schedule)
            except ValueError:
                logger.warning(
                    "invalid_cron_schedule",
                    name=name,
                    schedule=schedule,
                )
                continue

            trigger = CronTrigger(**cron_kwargs)
            job = self._scheduler.add_job(
                callback,
                trigger=trigger,
                args=[name],
                id=f"bsage-{name}",
                name=f"BSage: {name}",
            )
            self._jobs[name] = job.id
            logger.info("trigger_registered", name=name, schedule=schedule)

    def register_new_triggers(self, new_entries: dict[str, Any]) -> None:
        """Register cron triggers for newly discovered entries only.

        Unlike ``register_triggers()``, this method skips entries
        that already have a registered job, making it safe to call
        repeatedly with incremental additions.
        """
        for name, meta in new_entries.items():
            if name in self._jobs:
                continue
            if not meta.trigger or meta.trigger.get("type") != "cron":
                continue

            if meta.category == "input":
                callback = self._on_input_trigger
            elif meta.category == "process":
                callback = self._on_process_trigger
            else:
                continue

            schedule = meta.trigger.get("schedule", "")
            try:
                cron_kwargs = self._parse_cron(schedule)
            except ValueError:
                logger.warning(
                    "invalid_cron_schedule",
                    name=name,
                    schedule=schedule,
                )
                continue

            trigger = CronTrigger(**cron_kwargs)
            job = self._scheduler.add_job(
                callback,
                trigger=trigger,
                args=[name],
                id=f"bsage-{name}",
                name=f"BSage: {name}",
            )
            self._jobs[name] = job.id
            logger.info("trigger_hot_registered", name=name, schedule=schedule)

    def start(self) -> None:
        """Start the AsyncIO scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("scheduler_started")

    def stop(self) -> None:
        """Stop the AsyncIO scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown()
            logger.info("scheduler_stopped")

    @staticmethod
    def _parse_cron(schedule: str) -> dict[str, str]:
        """Parse a 5-field cron expression into APScheduler kwargs.

        Args:
            schedule: Cron expression like "*/15 * * * *".

        Returns:
            Dict with keys: minute, hour, day, month, day_of_week.

        Raises:
            ValueError: If the expression doesn't have exactly 5 fields.
        """
        parts = schedule.strip().split()
        if len(parts) != len(_CRON_FIELDS):
            raise ValueError(f"Invalid cron expression: '{schedule}'. Expected 5 fields.")
        return dict(zip(_CRON_FIELDS, parts, strict=True))

    async def _on_input_trigger(self, name: str) -> None:
        """Handle a cron trigger for an input plugin.

        Runs the plugin and feeds results into AgentLoop via on_input.
        """
        logger.info("trigger_fired", name=name, category="input")
        await emit_event(self._event_bus, "TRIGGER_FIRED", {"name": name, "category": "input"})
        try:
            context = self._agent_loop.build_context()
            meta = self._agent_loop.get_entry(name)
            result = await self._runner.run(meta, context)
            await self._agent_loop.on_input(name, result)
        except Exception:
            logger.exception("trigger_execution_failed", name=name)

    async def _on_process_trigger(self, name: str) -> None:
        """Handle a cron trigger for a process plugin/skill.

        Runs the entry directly and writes an action log.
        SafeModeGuard check is performed before execution.
        """
        logger.info("trigger_fired", name=name, category="process")
        await emit_event(self._event_bus, "TRIGGER_FIRED", {"name": name, "category": "process"})
        try:
            meta = self._agent_loop.get_entry(name)

            approved = await self._safe_mode_guard.check(meta)
            if not approved:
                logger.warning("process_trigger_rejected_by_safe_mode", name=name)
                return

            context = self._agent_loop.build_context()
            result = await self._runner.run(meta, context)
            summary = json.dumps(result, default=str)
            await self._agent_loop.write_action(name, summary)
        except Exception:
            logger.exception("trigger_execution_failed", name=name)
