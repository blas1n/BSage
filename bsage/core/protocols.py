"""Shared protocols for cross-module dependency injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from bsage.core.skill_context import SkillContext


class RunnerLike(Protocol):
    """Protocol for objects that can execute plugins or skills."""

    async def run(self, meta: Any, context: SkillContext) -> dict: ...


class NotifyRunnerLike(Protocol):
    """Protocol for runners that support notification entrypoints."""

    async def run_notify(self, meta: Any, context: SkillContext) -> dict: ...


class ContextBuilderLike(Protocol):
    """Protocol for callables that create a SkillContext."""

    def __call__(self, *, input_data: dict[str, Any] | None = None) -> SkillContext: ...


class SchedulerSupport(Protocol):
    """Protocol defining the interface that Scheduler requires from AgentLoop."""

    def build_context(
        self, input_data: dict[str, Any] | None = None, *, for_entry: str | None = None
    ) -> SkillContext: ...

    def get_entry(self, name: str) -> Any: ...

    async def on_input(
        self, plugin_name: str, raw_data: dict[str, Any]
    ) -> list[dict[str, Any]]: ...

    async def write_action(self, name: str, summary: str) -> None: ...
