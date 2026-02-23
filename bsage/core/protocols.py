"""Shared protocols for cross-module dependency injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from bsage.core.skill_context import SkillContext
    from bsage.core.skill_loader import SkillMeta


class SkillRunnerLike(Protocol):
    """Protocol for objects that can execute skills."""

    async def run(self, skill_meta: SkillMeta, context: SkillContext) -> dict: ...


class NotifyRunnerLike(Protocol):
    """Protocol for skill runners that support notification entrypoints."""

    async def run_notify(self, skill_meta: SkillMeta, context: SkillContext) -> dict: ...


class ContextBuilderLike(Protocol):
    """Protocol for callables that create a SkillContext."""

    def __call__(self, *, input_data: dict[str, Any] | None = None) -> SkillContext: ...


class SchedulerSupport(Protocol):
    """Protocol defining the interface that Scheduler requires from AgentLoop."""

    def build_context(self, input_data: dict[str, Any] | None = None) -> SkillContext: ...

    def get_skill(self, name: str) -> SkillMeta: ...

    async def on_input(self, skill_name: str, raw_data: dict[str, Any]) -> list[dict[str, Any]]: ...

    async def write_action(self, skill_name: str, summary: str) -> None: ...
