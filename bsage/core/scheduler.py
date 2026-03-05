"""Scheduler — registers cron and polling triggers for plugins/skills via APScheduler."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bsage.core.events import emit_event
from bsage.core.plugin_runner import MissingCredentialError

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.core.protocols import SchedulerSupport
    from bsage.core.runner import Runner
    from bsage.core.safe_mode import SafeModeGuard

logger = structlog.get_logger(__name__)

_CRON_FIELDS = ("minute", "hour", "day", "month", "day_of_week")
_POLLING_BACKOFF_INITIAL = 2.0
_POLLING_BACKOFF_MAX = 60.0
_POLLING_BACKOFF_FACTOR = 1.8


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
        self._polling_tasks: dict[str, asyncio.Task] = {}  # name -> asyncio.Task

    def register_triggers(self, registry: dict[str, Any]) -> None:
        """Register cron and polling triggers for input and process plugins/skills."""
        for name, meta in registry.items():
            if not meta.trigger:
                continue

            trigger_type = meta.trigger.get("type")

            if trigger_type == "polling":
                self._register_polling(name, meta)
                continue

            if trigger_type != "cron":
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
        """Register cron/polling triggers for newly discovered entries only.

        Unlike ``register_triggers()``, this method skips entries
        that already have a registered job, making it safe to call
        repeatedly with incremental additions.
        """
        for name, meta in new_entries.items():
            if name in self._jobs or name in self._polling_tasks:
                continue
            if not meta.trigger:
                continue

            trigger_type = meta.trigger.get("type")

            if trigger_type == "polling":
                self._register_polling(name, meta)
                continue

            if trigger_type != "cron":
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

    def _register_polling(self, name: str, meta: Any) -> None:
        """Register a polling trigger as a background asyncio task."""
        if name in self._polling_tasks:
            return
        task = asyncio.create_task(self._polling_loop(name, meta))
        self._polling_tasks[name] = task
        logger.info("polling_trigger_registered", name=name)

    async def _polling_loop(self, name: str, meta: Any) -> None:
        """Continuous polling loop with exponential backoff on errors."""
        backoff = _POLLING_BACKOFF_INITIAL
        while True:
            try:
                await self._on_input_trigger(name)
                backoff = _POLLING_BACKOFF_INITIAL  # reset on success
                await asyncio.sleep(0)  # yield control between iterations
            except MissingCredentialError:
                logger.warning(
                    "polling_skipped_missing_credentials",
                    name=name,
                    hint=f"Run: bsage setup {name}",
                )
                await emit_event(
                    self._event_bus,
                    "CREDENTIAL_SETUP_REQUIRED",
                    {"name": name, "category": "input"},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * _POLLING_BACKOFF_FACTOR, _POLLING_BACKOFF_MAX)
            except asyncio.CancelledError:
                logger.info("polling_stopped", name=name)
                return
            except Exception:
                logger.exception("polling_error", name=name, backoff_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * _POLLING_BACKOFF_FACTOR, _POLLING_BACKOFF_MAX)

    def start(self) -> None:
        """Start the AsyncIO scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("scheduler_started")

    def stop(self) -> None:
        """Stop the AsyncIO scheduler and cancel polling tasks."""
        for name, task in self._polling_tasks.items():
            task.cancel()
            logger.debug("polling_task_cancelled", name=name)
        self._polling_tasks.clear()
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
        except MissingCredentialError:
            logger.warning(
                "trigger_skipped_missing_credentials",
                name=name,
                hint=f"Run: bsage setup {name}",
            )
            await emit_event(
                self._event_bus,
                "CREDENTIAL_SETUP_REQUIRED",
                {"name": name, "category": "input"},
            )
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
        except MissingCredentialError:
            logger.warning(
                "trigger_skipped_missing_credentials",
                name=name,
                hint=f"Run: bsage setup {name}",
            )
            await emit_event(
                self._event_bus,
                "CREDENTIAL_SETUP_REQUIRED",
                {"name": name, "category": "process"},
            )
        except Exception:
            logger.exception("trigger_execution_failed", name=name)
