"""SyncManager — extensible vault sync after writes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from bsage.core.protocols import ContextBuilderLike, SkillRunnerLike

if TYPE_CHECKING:
    from bsage.core.skill_loader import SkillMeta

logger = structlog.get_logger(__name__)


class WriteEventType(Enum):
    """Type of vault write operation."""

    SEED = "seed"
    GARDEN = "garden"
    ACTION = "action"


@dataclass
class WriteEvent:
    """Describes a vault write that just occurred."""

    event_type: WriteEventType
    path: Path
    source: str


@runtime_checkable
class SyncBackend(Protocol):
    """Protocol for vault synchronization backends.

    Implementations (e.g. S3SyncBackend, GitSyncBackend) are registered
    with SyncManager and notified after every vault write.
    """

    @property
    def name(self) -> str: ...

    async def sync(self, event: WriteEvent) -> None: ...


class SyncManager:
    """Manages registered sync backends and dispatches write events.

    Sync failures are logged but never propagated — local writes always
    succeed regardless of sync backend status.
    """

    def __init__(self) -> None:
        self._backends: dict[str, SyncBackend] = {}
        self._output_skills: list[SkillMeta] = []
        self._skill_runner: SkillRunnerLike | None = None
        self._context_builder: ContextBuilderLike | None = None

    def register(self, backend: SyncBackend) -> None:
        """Register a sync backend."""
        self._backends[backend.name] = backend
        logger.info("sync_backend_registered", name=backend.name)

    def unregister(self, name: str) -> None:
        """Remove a sync backend by name.

        Raises:
            KeyError: If the backend is not registered.
        """
        del self._backends[name]
        logger.info("sync_backend_unregistered", name=name)

    def list_backends(self) -> list[str]:
        """Return names of all registered backends."""
        return list(self._backends.keys())

    def register_output_skills(
        self,
        skills: list[SkillMeta],
        skill_runner: SkillRunnerLike,
        context_builder: ContextBuilderLike,
    ) -> None:
        """Register output skills for execution on write events.

        Replaces any previously registered output skills.

        Args:
            skills: List of output category SkillMeta.
            skill_runner: SkillRunner instance to execute skills.
            context_builder: Callable(input_data=dict) -> SkillContext.
        """
        self._output_skills = []
        self._skill_runner = skill_runner
        self._context_builder = context_builder
        for s in skills:
            if s.category != "output":
                logger.warning(
                    "non_output_skill_rejected",
                    name=s.name,
                    category=s.category,
                )
                continue
            self._output_skills.append(s)
            logger.info("output_skill_registered", name=s.name)

    async def notify(self, event: WriteEvent) -> None:
        """Notify all registered backends of a write event.

        Each backend is called independently. Failures are logged
        but never propagated — the local write has already succeeded.
        """
        for name, backend in self._backends.items():
            try:
                await backend.sync(event)
                logger.debug("sync_backend_notified", backend=name, path=str(event.path))
            except Exception:
                logger.warning(
                    "sync_backend_failed",
                    backend=name,
                    path=str(event.path),
                    exc_info=True,
                )

        # Execute output skills
        if self._skill_runner and self._context_builder:
            event_data = {
                "event_type": event.event_type.value,
                "path": str(event.path),
                "source": event.source,
            }
            for meta in self._output_skills:
                try:
                    context = self._context_builder(input_data=event_data)
                    await self._skill_runner.run(meta, context)
                    logger.debug("output_skill_executed", skill=meta.name)
                except Exception:
                    logger.warning(
                        "output_skill_failed",
                        skill=meta.name,
                        exc_info=True,
                    )
