"""Tests for POST /api/notify endpoint."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.plugin_loader import PluginMeta
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes


def _make_plugin_meta(name: str, *, has_notify: bool = True) -> PluginMeta:
    """Create a PluginMeta with an optional notify handler."""
    notify_fn = AsyncMock(return_value={"sent": True}) if has_notify else None
    return PluginMeta(
        name=name,
        version="1.0.0",
        category="input",
        description=f"Test {name} plugin",
        _execute_fn=AsyncMock(),
        _notify_fn=notify_fn,
    )


def _make_state(tmp_path: Path, *, registry: dict | None = None) -> MagicMock:
    """Create a mocked AppState with optional plugin registry."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.vault = MagicMock()
    state.vault.root = vault_root
    state.vault.read_notes = AsyncMock(return_value=[])
    state.runtime_config = RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.sync_manager = SyncManager()
    state.danger_map = {}
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    state.retriever = MagicMock()
    state.retriever.index_available = False
    state.embedder = MagicMock()
    state.embedder.enabled = False
    state.vector_store = MagicMock()
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.chat_bridge = AsyncMock()
    state.garden_writer = AsyncMock()
    state.llm_client = MagicMock()

    # Agent loop with registry
    agent_loop = MagicMock()
    agent_loop._registry = registry or {}
    agent_loop._runner = MagicMock()
    agent_loop._garden_writer = state.garden_writer
    agent_loop._llm_client = state.llm_client
    state.agent_loop = agent_loop

    # Runner
    state.runner = MagicMock()
    state.runner.run_notify = AsyncMock(return_value={"sent": True})

    # Ontology mock
    ontology = MagicMock()
    ontology.get_entity_types.return_value = {}
    state.ontology = ontology

    async def _mock_get_current_user():
        return MagicMock(id="test-user", email="test@example.com", role="authenticated")

    state.get_current_user = _mock_get_current_user
    state.auth_provider = None
    return state


@pytest.fixture()
def telegram_plugin():
    return _make_plugin_meta("telegram-input")


@pytest.fixture()
def slack_plugin():
    return _make_plugin_meta("slack-input")


@pytest.fixture()
def no_notify_plugin():
    return _make_plugin_meta("calendar-input", has_notify=False)


class TestNotifyEndpointSuccess:
    """Tests for successful notification sends."""

    def test_send_notification_auto_route(self, tmp_path, telegram_plugin):
        """Auto-routes to first available notify channel when no channel specified."""
        registry = {"telegram-input": telegram_plugin}
        state = _make_state(tmp_path, registry=registry)
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": "Hello from BSNexus"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert data["channel"] == "telegram-input"
        assert data["error"] is None
        state.runner.run_notify.assert_awaited_once()

    def test_send_notification_specific_channel(self, tmp_path, telegram_plugin, slack_plugin):
        """Routes to specific channel when channel is specified."""
        registry = {"telegram-input": telegram_plugin, "slack-input": slack_plugin}
        state = _make_state(tmp_path, registry=registry)
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post(
            "/api/notify",
            json={"message": "Hello", "channel": "slack-input"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert data["channel"] == "slack-input"

    def test_send_notification_with_metadata(self, tmp_path, telegram_plugin):
        """Metadata is passed through to the notify handler via input_data."""
        registry = {"telegram-input": telegram_plugin}
        state = _make_state(tmp_path, registry=registry)
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post(
            "/api/notify",
            json={
                "message": "Alert!",
                "metadata": {"inline_keyboard": [[{"text": "OK"}]]},
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        # Verify that run_notify was called with metadata in context
        call_args = state.runner.run_notify.call_args
        ctx = call_args[0][1]  # second positional arg is context
        assert ctx.input_data["message"] == "Alert!"
        assert ctx.input_data["metadata"] == {"inline_keyboard": [[{"text": "OK"}]]}


class TestNotifyEndpointNoChannels:
    """Tests for when no notification channels are available."""

    def test_no_channels_configured(self, tmp_path):
        """Returns sent=False when no plugins have notify handlers."""
        state = _make_state(tmp_path, registry={})
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": "Hello"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert data["channel"] is None
        assert "no notification channel" in data["error"].lower()

    def test_only_plugins_without_notify(self, tmp_path, no_notify_plugin):
        """Returns sent=False when plugins exist but none have notify handlers."""
        registry = {"calendar-input": no_notify_plugin}
        state = _make_state(tmp_path, registry=registry)
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": "Hello"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert "no notification channel" in data["error"].lower()

    def test_specific_channel_not_found(self, tmp_path, telegram_plugin):
        """Returns sent=False when specified channel doesn't exist."""
        registry = {"telegram-input": telegram_plugin}
        state = _make_state(tmp_path, registry=registry)
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post(
            "/api/notify",
            json={"message": "Hello", "channel": "nonexistent"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert "nonexistent" in data["error"].lower()

    def test_specific_channel_has_no_notify_fn(self, tmp_path, no_notify_plugin):
        """Returns sent=False when specified channel plugin has no notify handler."""
        registry = {"calendar-input": no_notify_plugin}
        state = _make_state(tmp_path, registry=registry)
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post(
            "/api/notify",
            json={"message": "Hello", "channel": "calendar-input"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert "no notify handler" in data["error"].lower()


class TestNotifyEndpointAuth:
    """Tests for authentication on the notify endpoint."""

    def test_auth_required_401(self, tmp_path):
        """Returns 401 when auth is enabled and no token provided."""
        from bsvibe_auth import AuthError, BSVibeUser, SupabaseAuthProvider

        from bsage.gateway.auth import create_get_current_user

        state = _make_state(tmp_path, registry={})

        # Create a real auth provider mock that rejects requests
        mock_provider = MagicMock(spec=SupabaseAuthProvider)

        async def _reject(token: str) -> BSVibeUser:
            raise AuthError("Invalid token")

        mock_provider.verify_token = _reject

        state.get_current_user = create_get_current_user(mock_provider, service_api_keys={})

        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": "Hello"})
        assert resp.status_code == 401


class TestNotifyEndpointValidation:
    """Tests for request validation."""

    def test_empty_message_422(self, tmp_path):
        """Returns 422 when message is empty."""
        state = _make_state(tmp_path, registry={})
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": ""})
        assert resp.status_code == 422

    def test_missing_message_422(self, tmp_path):
        """Returns 422 when message field is missing."""
        state = _make_state(tmp_path, registry={})
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={})
        assert resp.status_code == 422


class TestNotifyEndpointErrors:
    """Tests for error handling during notification send."""

    def test_runner_exception_returns_error(self, tmp_path, telegram_plugin):
        """Returns sent=False with error message when runner raises."""
        registry = {"telegram-input": telegram_plugin}
        state = _make_state(tmp_path, registry=registry)
        state.runner.run_notify = AsyncMock(side_effect=RuntimeError("Connection refused"))
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": "Hello"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert "Connection refused" in data["error"]

    def test_gateway_not_initialized(self, tmp_path):
        """Returns 503 when agent_loop is None (gateway not ready)."""
        state = _make_state(tmp_path, registry={})
        state.agent_loop = None
        app = FastAPI()
        app.include_router(create_routes(state))
        client = TestClient(app)

        resp = client.post("/api/notify", json={"message": "Hello"})
        assert resp.status_code == 503
