"""Scheduler — registers cron triggers for input and process skills via APScheduler."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from bsage.core.protocols import SchedulerSupport
    from bsage.core.safe_mode import SafeModeGuard
    from bsage.core.skill_loader import SkillMeta
    from bsage.core.skill_runner import SkillRunner

logger = structlog.get_logger(__name__)

_CRON_FIELDS = ("minute", "hour", "day", "month", "day_of_week")


class Scheduler:
    """Registers and manages cron triggers for input and process skills."""

    def __init__(
        self,
        agent_loop: SchedulerSupport,
        skill_runner: SkillRunner,
        safe_mode_guard: SafeModeGuard,
    ) -> None:
        self._agent_loop = agent_loop
        self._skill_runner = skill_runner
        self._safe_mode_guard = safe_mode_guard
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[str, str] = {}  # skill_name -> job_id

    def register_triggers(self, registry: dict[str, SkillMeta]) -> None:
        """Register cron triggers for input and process skills."""
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
                    skill=name,
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
            logger.info("trigger_registered", skill=name, schedule=schedule)

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

    async def _on_input_trigger(self, skill_name: str) -> None:
        """Handle a cron trigger for an input skill.

        Runs the skill and feeds results into AgentLoop via on_input.
        """
        logger.info("trigger_fired", skill=skill_name, category="input")
        try:
            context = self._agent_loop.build_context()
            meta = self._agent_loop.get_skill(skill_name)
            result = await self._skill_runner.run(meta, context)
            await self._agent_loop.on_input(skill_name, result)
        except Exception:
            logger.exception("trigger_execution_failed", skill=skill_name)

    async def _on_process_trigger(self, skill_name: str) -> None:
        """Handle a cron trigger for a process skill.

        Runs the skill directly and writes an action log.
        SafeModeGuard check is performed before execution.
        """
        logger.info("trigger_fired", skill=skill_name, category="process")
        try:
            meta = self._agent_loop.get_skill(skill_name)

            approved = await self._safe_mode_guard.check(meta)
            if not approved:
                logger.warning("process_trigger_rejected_by_safe_mode", skill=skill_name)
                return

            context = self._agent_loop.build_context()
            result = await self._skill_runner.run(meta, context)
            summary = json.dumps(result, default=str)
            await self._agent_loop.write_action(skill_name, summary)
        except Exception:
            logger.exception("trigger_execution_failed", skill=skill_name)
