"""Tests for bsage.core.plugin_runner — Plugin Python execution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.exceptions import CredentialNotFoundError, MissingCredentialError, PluginRunError
from bsage.core.plugin_runner import PluginRunner
from bsage.tests.conftest import make_plugin_meta as _make_plugin_meta


class TestPluginRunnerRun:
    """Test PluginRunner.run() dispatches to _execute_fn."""

    async def test_run_calls_execute_fn(self, mock_context) -> None:
        execute_fn = AsyncMock(return_value={"status": "ok"})
        meta = _make_plugin_meta()
        meta._execute_fn = execute_fn

        runner = PluginRunner()
        result = await runner.run(meta, mock_context)

        execute_fn.assert_called_once_with(mock_context)
        assert result == {"status": "ok"}

    async def test_run_raises_plugin_run_error_when_no_execute_fn(self, mock_context) -> None:
        meta = _make_plugin_meta()
        # _execute_fn is None by default
        runner = PluginRunner()
        with pytest.raises(PluginRunError, match="has no execute function"):
            await runner.run(meta, mock_context)

    async def test_run_wraps_exception_in_plugin_run_error(self, mock_context) -> None:
        execute_fn = AsyncMock(side_effect=RuntimeError("network error"))
        meta = _make_plugin_meta()
        meta._execute_fn = execute_fn

        runner = PluginRunner()
        with pytest.raises(PluginRunError, match="network error"):
            await runner.run(meta, mock_context)


class TestPluginRunnerRunNotify:
    """Test PluginRunner.run_notify() dispatches to _notify_fn."""

    async def test_run_notify_calls_notify_fn(self, mock_context) -> None:
        notify_fn = AsyncMock(return_value={"sent": True})
        meta = _make_plugin_meta()
        meta._notify_fn = notify_fn

        runner = PluginRunner()
        result = await runner.run_notify(meta, mock_context)

        notify_fn.assert_called_once_with(mock_context)
        assert result == {"sent": True}

    async def test_run_notify_raises_when_no_notify_fn(self, mock_context) -> None:
        meta = _make_plugin_meta()
        # _notify_fn is None by default
        runner = PluginRunner()
        with pytest.raises(PluginRunError, match="no notification handler"):
            await runner.run_notify(meta, mock_context)

    async def test_run_notify_wraps_exception(self, mock_context) -> None:
        notify_fn = AsyncMock(side_effect=RuntimeError("send failed"))
        meta = _make_plugin_meta()
        meta._notify_fn = notify_fn

        runner = PluginRunner()
        with pytest.raises(PluginRunError, match="send failed"):
            await runner.run_notify(meta, mock_context)


class TestPluginRunnerCredentials:
    """Test credential auto-injection via CredentialStore."""

    async def test_credentials_injected_when_available(self, mock_context) -> None:
        execute_fn = AsyncMock(return_value={"status": "ok"})
        meta = _make_plugin_meta()
        meta._execute_fn = execute_fn

        cred_store = MagicMock()
        cred_store.get = AsyncMock(return_value={"api_key": "secret"})

        runner = PluginRunner(credential_store=cred_store)
        await runner.run(meta, mock_context)

        assert mock_context.credentials == {"api_key": "secret"}

    async def test_no_credentials_declared_does_not_fail(self, mock_context) -> None:
        """Plugin with credentials=None (no declaration) runs fine without stored creds."""
        execute_fn = AsyncMock(return_value={"status": "ok"})
        meta = _make_plugin_meta()  # credentials=None by default
        meta._execute_fn = execute_fn

        cred_store = MagicMock()
        cred_store.get = AsyncMock(side_effect=CredentialNotFoundError("no creds"))

        runner = PluginRunner(credential_store=cred_store)
        result = await runner.run(meta, mock_context)
        assert result["status"] == "ok"
        assert mock_context.credentials == {}

    async def test_no_credential_store_skips_injection(self, mock_context) -> None:
        execute_fn = AsyncMock(return_value={"status": "ok"})
        meta = _make_plugin_meta()
        meta._execute_fn = execute_fn

        runner = PluginRunner()  # no credential_store
        result = await runner.run(meta, mock_context)
        assert result["status"] == "ok"
        assert mock_context.credentials == {}

    async def test_credentials_injected_before_execute(self, mock_context) -> None:
        """Credentials must be available in context when execute_fn is called."""
        captured_creds = {}

        async def execute_fn(ctx):
            captured_creds.update(ctx.credentials)
            return {}

        meta = _make_plugin_meta()
        meta._execute_fn = execute_fn

        cred_store = MagicMock()
        cred_store.get = AsyncMock(return_value={"token": "abc123"})

        runner = PluginRunner(credential_store=cred_store)
        await runner.run(meta, mock_context)

        assert captured_creds == {"token": "abc123"}


class TestPluginRunnerEvents:
    """Test EventBus emission from PluginRunner."""

    async def test_emits_start_and_complete_events(self, mock_context) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        meta = _make_plugin_meta()
        meta._execute_fn = AsyncMock(return_value={"ok": True})
        runner = PluginRunner(event_bus=event_bus)
        await runner.run(meta, mock_context)

        assert sub.on_event.call_count == 2
        start_event = sub.on_event.call_args_list[0].args[0]
        complete_event = sub.on_event.call_args_list[1].args[0]
        assert start_event.event_type == EventType.PLUGIN_RUN_START
        assert complete_event.event_type == EventType.PLUGIN_RUN_COMPLETE
        assert start_event.correlation_id == complete_event.correlation_id

    async def test_emits_error_event_on_failure(self, mock_context) -> None:
        from bsage.core.events import EventBus, EventType

        event_bus = EventBus()
        sub = AsyncMock()
        event_bus.subscribe(sub)

        meta = _make_plugin_meta()
        meta._execute_fn = AsyncMock(side_effect=RuntimeError("fail"))
        runner = PluginRunner(event_bus=event_bus)

        with pytest.raises(PluginRunError):
            await runner.run(meta, mock_context)

        events = [c.args[0] for c in sub.on_event.call_args_list]
        types = [e.event_type for e in events]
        assert EventType.PLUGIN_RUN_START in types
        assert EventType.PLUGIN_RUN_ERROR in types

    async def test_no_events_when_event_bus_is_none(self, mock_context) -> None:
        meta = _make_plugin_meta()
        meta._execute_fn = AsyncMock(return_value={"ok": True})
        runner = PluginRunner()  # no event_bus
        result = await runner.run(meta, mock_context)
        assert result == {"ok": True}


class TestCredentialValidation:
    """Test required credential validation in PluginRunner."""

    async def test_raises_when_required_creds_missing(self, mock_context) -> None:
        meta = _make_plugin_meta(
            credentials=[{"name": "api_key", "description": "Key", "required": True}],
        )
        meta._execute_fn = AsyncMock(return_value={})

        cred_store = MagicMock()
        cred_store.get = AsyncMock(side_effect=CredentialNotFoundError("no creds"))

        runner = PluginRunner(credential_store=cred_store)
        with pytest.raises(MissingCredentialError, match="bsage setup test-plugin"):
            await runner.run(meta, mock_context)

    async def test_ok_when_only_optional_missing(self, mock_context) -> None:
        meta = _make_plugin_meta(
            credentials=[{"name": "debug_mode", "description": "Debug", "required": False}],
        )
        meta._execute_fn = AsyncMock(return_value={"ok": True})

        cred_store = MagicMock()
        cred_store.get = AsyncMock(side_effect=CredentialNotFoundError("no creds"))

        runner = PluginRunner(credential_store=cred_store)
        result = await runner.run(meta, mock_context)
        assert result == {"ok": True}

    async def test_raises_when_required_field_missing_from_stored(self, mock_context) -> None:
        meta = _make_plugin_meta(
            credentials=[
                {"name": "api_key", "description": "Key", "required": True},
                {"name": "secret", "description": "Secret", "required": True},
            ],
        )
        meta._execute_fn = AsyncMock(return_value={})

        cred_store = MagicMock()
        cred_store.get = AsyncMock(return_value={"api_key": "val"})  # secret missing

        runner = PluginRunner(credential_store=cred_store)
        with pytest.raises(MissingCredentialError, match="secret"):
            await runner.run(meta, mock_context)

    async def test_ok_when_all_required_present(self, mock_context) -> None:
        meta = _make_plugin_meta(
            credentials=[
                {"name": "api_key", "description": "Key", "required": True},
                {"name": "extra", "description": "Extra", "required": False},
            ],
        )
        meta._execute_fn = AsyncMock(return_value={"ok": True})

        cred_store = MagicMock()
        cred_store.get = AsyncMock(return_value={"api_key": "val"})

        runner = PluginRunner(credential_store=cred_store)
        result = await runner.run(meta, mock_context)
        assert result == {"ok": True}

    async def test_ok_when_no_credentials_declared(self, mock_context) -> None:
        meta = _make_plugin_meta()  # credentials=None
        meta._execute_fn = AsyncMock(return_value={"ok": True})

        cred_store = MagicMock()
        cred_store.get = AsyncMock(side_effect=CredentialNotFoundError("no creds"))

        runner = PluginRunner(credential_store=cred_store)
        result = await runner.run(meta, mock_context)
        assert result == {"ok": True}
