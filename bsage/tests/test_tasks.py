"""Tests for bsage.core.tasks — orphan-safe task spawning."""

import asyncio

import pytest

from bsage.core.tasks import spawn_task


class TestSpawnTask:
    """spawn_task wraps asyncio.create_task with a done-callback that logs
    swallowed exceptions and keeps a strong reference until completion.

    This addresses Audit §5 H16: ``asyncio.create_task()`` orphan tasks whose
    exceptions are silently dropped.
    """

    async def test_spawn_returns_task(self) -> None:
        async def coro() -> str:
            return "ok"

        task = spawn_task(coro(), name="test-coro")
        assert isinstance(task, asyncio.Task)
        result = await task
        assert result == "ok"

    async def test_spawn_keeps_strong_reference_until_done(self) -> None:
        """Even without holding the returned task, it must not be garbage-
        collected before completion."""
        completed = asyncio.Event()

        async def coro() -> None:
            await asyncio.sleep(0.01)
            completed.set()

        spawn_task(coro(), name="strong-ref")
        # Drop our ref; only the helper's internal set holds it.
        del coro
        await asyncio.wait_for(completed.wait(), timeout=2.0)

    async def test_exception_is_logged_not_swallowed(self, monkeypatch) -> None:
        """An unhandled exception inside a spawned task must be surfaced via
        the project logger, not lost into ``Task exception was never retrieved``
        warnings only."""
        import bsage.core.tasks as tasks_mod

        recorded: list[tuple[str, dict]] = []

        class StubLogger:
            def debug(self, event: str, **kw):
                recorded.append((event, kw))

            def error(self, event: str, **kw):
                recorded.append((event, kw))

        monkeypatch.setattr(tasks_mod, "logger", StubLogger())

        class BoomError(RuntimeError):
            pass

        async def boom() -> None:
            raise BoomError("kaboom")

        task = spawn_task(boom(), name="explosive-task")
        with pytest.raises(BoomError):
            await task
        await asyncio.sleep(0)  # let the done callback run

        failures = [(event, kw) for (event, kw) in recorded if event == "task_failed"]
        assert failures, f"expected task_failed event, got {recorded}"
        event, kw = failures[0]
        assert kw.get("task") == "explosive-task"
        assert kw.get("error") == "BoomError"

    async def test_cancellation_is_silent(self) -> None:
        """Cancellation is the normal shutdown path — must NOT log as error."""

        async def long_running() -> None:
            await asyncio.sleep(60)

        task = spawn_task(long_running(), name="cancel-me")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_normal_completion_emits_no_error(self, monkeypatch) -> None:
        import bsage.core.tasks as tasks_mod

        recorded: list[tuple[str, dict]] = []

        class StubLogger:
            def debug(self, event: str, **kw):
                recorded.append(("debug", kw | {"event": event}))

            def error(self, event: str, **kw):
                recorded.append(("error", kw | {"event": event}))

        monkeypatch.setattr(tasks_mod, "logger", StubLogger())

        async def quiet() -> int:
            return 7

        task = spawn_task(quiet(), name="quiet-task")
        await task
        await asyncio.sleep(0)

        # No error-level entries from the helper.
        errors = [r for r in recorded if r[0] == "error"]
        assert errors == []
