"""NotificationInterface — protocol and router for sending user notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from bsage.core.protocols import ContextBuilderLike, NotifyRunnerLike

if TYPE_CHECKING:
    from bsage.core.skill_loader import SkillMeta

logger = structlog.get_logger(__name__)


@runtime_checkable
class NotificationInterface(Protocol):
    """Interface for delivering messages to the user.

    Process skills use context.notify.send() to notify the user.
    The framework mediates channel selection (CLI, Telegram, etc.).
    """

    async def send(self, message: str, level: str = "info") -> None: ...


class NotificationRouter:
    """Routes notifications through input skills that have a notification_entrypoint.

    Input skills with notification_entrypoint (e.g. "skill.py::notify") can
    send messages back through the same channel they receive from.
    Example: a Telegram input skill can also send notifications via the same bot.

    Auto-discovers notification-capable skills from the registry during setup().
    """

    def __init__(self) -> None:
        self._skills: list[SkillMeta] = []
        self._skill_runner: NotifyRunnerLike | None = None
        self._context_builder: ContextBuilderLike | None = None

    def setup(
        self,
        registry: dict[str, SkillMeta],
        skill_runner: NotifyRunnerLike,
        context_builder: ContextBuilderLike,
    ) -> None:
        """Auto-discover notification-capable skills from the registry.

        Finds all skills with a notification_entrypoint and registers them.

        Args:
            registry: Full skill registry to scan.
            skill_runner: SkillRunner instance with run_notify support.
            context_builder: Callable(input_data=dict) -> SkillContext.
        """
        self._skills = [meta for meta in registry.values() if meta.notification_entrypoint]
        self._skill_runner = skill_runner
        self._context_builder = context_builder
        if self._skills:
            logger.info(
                "notification_channels_discovered",
                skills=[m.name for m in self._skills],
            )

    async def send(self, message: str, level: str = "info") -> None:
        """Send a notification through discovered notification skills.

        Each skill's notification_entrypoint is called with
        input_data={"message": ..., "level": ...}.
        context.notify is set to None to prevent recursion.

        Falls back silently (log only) when no skills are available.
        """
        if not self._skills or not self._skill_runner or not self._context_builder:
            logger.info("notification_no_channel", level=level)
            return

        for meta in self._skills:
            try:
                ctx = self._context_builder(
                    input_data={"message": message, "level": level},
                )
                # Prevent recursion: notification skills cannot send notifications
                ctx.notify = None
                await self._skill_runner.run_notify(meta, ctx)
                logger.info("notification_sent", skill=meta.name, level=level)
            except Exception:
                logger.warning(
                    "notification_skill_failed",
                    skill=meta.name,
                    exc_info=True,
                )
