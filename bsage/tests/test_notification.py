"""Tests for bsage.core.notification — NotificationRouter skill routing."""

from unittest.mock import AsyncMock, MagicMock

from bsage.core.notification import NotificationRouter
from bsage.core.skill_loader import SkillMeta


def _make_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "telegram-input",
        "version": "1.0.0",
        "category": "input",
        "is_dangerous": False,
        "description": "Receive and send messages via Telegram",
    }
    defaults.update(overrides)
    return SkillMeta(**defaults)


class TestNotificationRouterSetup:
    """Test auto-discovery from registry."""

    def test_setup_discovers_notification_capable_skills(self) -> None:
        router = NotificationRouter()
        registry = {
            "telegram-input": _make_meta(
                notification_entrypoint="skill.py::notify",
            ),
            "calendar-input": _make_meta(
                name="calendar-input",
                description="Fetch calendar events",
            ),
        }
        router.setup(registry, MagicMock(), MagicMock())
        assert len(router._skills) == 1
        assert router._skills[0].name == "telegram-input"

    def test_setup_finds_multiple_channels(self) -> None:
        router = NotificationRouter()
        registry = {
            "telegram-input": _make_meta(
                notification_entrypoint="skill.py::notify",
            ),
            "slack-input": _make_meta(
                name="slack-input",
                notification_entrypoint="skill.py::notify",
            ),
        }
        router.setup(registry, MagicMock(), MagicMock())
        assert len(router._skills) == 2

    def test_setup_with_no_notification_skills(self) -> None:
        router = NotificationRouter()
        registry = {
            "calendar-input": _make_meta(name="calendar-input"),
        }
        router.setup(registry, MagicMock(), MagicMock())
        assert len(router._skills) == 0


class TestNotificationRouterSend:
    """Test notification delivery through skills."""

    async def test_send_calls_run_notify(self) -> None:
        router = NotificationRouter()
        runner = MagicMock()
        runner.run_notify = AsyncMock(return_value={"sent": True})
        ctx = MagicMock()
        builder = MagicMock(return_value=ctx)

        registry = {
            "telegram-input": _make_meta(
                notification_entrypoint="skill.py::notify",
            ),
        }
        router.setup(registry, runner, builder)
        await router.send("Hello!", level="info")

        runner.run_notify.assert_called_once()
        builder.assert_called_once_with(
            input_data={"message": "Hello!", "level": "info"},
        )

    async def test_send_sets_notify_none_to_prevent_recursion(self) -> None:
        router = NotificationRouter()
        runner = MagicMock()
        runner.run_notify = AsyncMock(return_value={})
        ctx = MagicMock()
        ctx.notify = router  # would cause recursion if not cleared
        builder = MagicMock(return_value=ctx)

        registry = {
            "telegram-input": _make_meta(
                notification_entrypoint="skill.py::notify",
            ),
        }
        router.setup(registry, runner, builder)
        await router.send("test")

        assert ctx.notify is None

    async def test_send_executes_multiple_channels(self) -> None:
        router = NotificationRouter()
        runner = MagicMock()
        runner.run_notify = AsyncMock(return_value={})
        builder = MagicMock(return_value=MagicMock())

        registry = {
            "telegram-input": _make_meta(
                notification_entrypoint="skill.py::notify",
            ),
            "slack-input": _make_meta(
                name="slack-input",
                notification_entrypoint="skill.py::notify",
            ),
        }
        router.setup(registry, runner, builder)
        await router.send("broadcast")

        assert runner.run_notify.call_count == 2

    async def test_send_continues_on_skill_failure(self) -> None:
        router = NotificationRouter()
        runner = MagicMock()
        runner.run_notify = AsyncMock(
            side_effect=[RuntimeError("fail"), {"sent": True}],
        )
        builder = MagicMock(return_value=MagicMock())

        registry = {
            "broken-input": _make_meta(
                name="broken-input",
                notification_entrypoint="skill.py::notify",
            ),
            "working-input": _make_meta(
                name="working-input",
                notification_entrypoint="skill.py::notify",
            ),
        }
        router.setup(registry, runner, builder)
        await router.send("test")

        assert runner.run_notify.call_count == 2


class TestNotificationRouterFallback:
    """Test silent fallback when no channels available."""

    async def test_send_without_setup_does_not_raise(self) -> None:
        router = NotificationRouter()
        await router.send("hello")

    async def test_send_with_no_channels_does_not_raise(self) -> None:
        router = NotificationRouter()
        router.setup({}, MagicMock(), MagicMock())
        await router.send("hello")
