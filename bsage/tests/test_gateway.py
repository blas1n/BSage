"""Tests for bsage.gateway — FastAPI Gateway routes and lifecycle."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.config import Settings
from bsage.core.plugin_loader import PluginMeta
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.app import create_app
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import ConnectionManager
from bsage.tests.conftest import make_skill_meta as _make_meta


@pytest.fixture()
def mock_state():
    """Create a mocked AppState for route testing."""
    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(
        return_value={
            "garden-writer": _make_meta(name="garden-writer"),
            "calendar-input": _make_meta(name="calendar-input", category="input"),
        }
    )
    state.skill_loader.get = MagicMock(return_value=_make_meta(name="garden-writer"))
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader.get = MagicMock(return_value=_make_meta(name="garden-writer"))
    state.agent_loop = MagicMock()
    state.agent_loop.on_input = AsyncMock(return_value=[{"status": "ok"}])
    state.agent_loop.chat = AsyncMock(return_value="Mocked chat response")
    state.vault = MagicMock()
    state.vault.read_notes = AsyncMock(return_value=[])
    state.runtime_config = RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.sync_manager = SyncManager()
    state.llm_client = AsyncMock()
    state.llm_client.chat = AsyncMock(return_value="Mocked LLM response")
    state.garden_writer = AsyncMock()
    state.garden_writer.read_notes = AsyncMock(return_value=[])
    state.garden_writer.write_action = AsyncMock()
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="You are BSage.")
    state.prompt_registry.render = MagicMock(return_value="Chat instructions here.")
    state.danger_map = {}
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    state.retriever = MagicMock()
    state.retriever.index_available = False
    state.chat_bridge = AsyncMock()
    state.chat_bridge.chat = AsyncMock(return_value="Mocked chat response")
    return state


@pytest.fixture()
def test_app(mock_state):
    """Create a test FastAPI app with mocked state."""
    app = FastAPI()
    app.include_router(create_routes(mock_state))
    return app


@pytest.fixture()
def client(test_app):
    return TestClient(test_app)


class TestHealthEndpoint:
    """Test GET /api/health."""

    def test_health_returns_ok(self, client) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSkillsEndpoint:
    """Test GET /api/skills."""

    def test_list_skills_returns_all(self, client) -> None:
        response = client.get("/api/skills")
        assert response.status_code == 200
        skills = response.json()
        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert "garden-writer" in names
        assert "calendar-input" in names

    def test_list_skills_has_required_fields(self, client) -> None:
        response = client.get("/api/skills")
        skill = response.json()[0]
        assert "name" in skill
        assert "version" in skill
        assert "category" in skill
        assert "is_dangerous" in skill
        assert "description" in skill
        assert "has_credentials" in skill
        assert "credentials_configured" in skill


class TestCredentialStatusInMeta:
    """Test credential status fields in _meta_to_dict output."""

    def test_skill_without_credentials_shows_configured(self, client) -> None:
        response = client.get("/api/skills")
        skill = response.json()[0]
        assert skill["has_credentials"] is False
        assert skill["credentials_configured"] is True

    def test_plugin_with_credentials_unconfigured(self, client, mock_state) -> None:
        from bsage.core.plugin_loader import PluginMeta

        meta = PluginMeta(
            name="email-input",
            version="1.0.0",
            category="input",
            description="Email",
            credentials=[
                {"name": "email", "description": "Email", "required": True},
            ],
        )
        mock_state.plugin_loader.load_all = AsyncMock(return_value={"email-input": meta})
        mock_state.credential_store.list_services = MagicMock(return_value=[])

        response = client.get("/api/plugins")
        plugin = response.json()[0]
        assert plugin["has_credentials"] is True
        assert plugin["credentials_configured"] is False
        assert plugin["enabled"] is False

    def test_plugin_with_credentials_configured(self, client, mock_state) -> None:
        from bsage.core.plugin_loader import PluginMeta

        meta = PluginMeta(
            name="email-input",
            version="1.0.0",
            category="input",
            description="Email",
            credentials=[
                {"name": "email", "description": "Email", "required": True},
            ],
        )
        mock_state.plugin_loader.load_all = AsyncMock(return_value={"email-input": meta})
        mock_state.credential_store.list_services = MagicMock(return_value=["email-input"])

        response = client.get("/api/plugins")
        plugin = response.json()[0]
        assert plugin["has_credentials"] is True
        assert plugin["credentials_configured"] is True
        assert plugin["enabled"] is True

    def test_skill_with_dict_credentials_fields(self, client, mock_state) -> None:
        meta = _make_meta(
            name="custom-skill",
            credentials={
                "fields": [{"name": "token", "description": "API token", "required": True}],
            },
        )
        mock_state.skill_loader.load_all = AsyncMock(return_value={"custom-skill": meta})
        mock_state.credential_store.list_services = MagicMock(return_value=[])

        response = client.get("/api/skills")
        skill = response.json()[0]
        assert skill["has_credentials"] is True
        assert skill["credentials_configured"] is False
        assert skill["enabled"] is False


class TestRunSkillEndpoint:
    """Test POST /api/plugins/{name}/run."""

    def test_run_skill_returns_results(self, client) -> None:
        response = client.post("/api/plugins/garden-writer/run")
        assert response.status_code == 200
        data = response.json()
        assert data["plugin"] == "garden-writer"
        assert len(data["results"]) == 1

    def test_run_unknown_skill_returns_404(self, client, mock_state) -> None:
        from bsage.core.exceptions import PluginLoadError

        mock_state.plugin_loader.get = MagicMock(side_effect=PluginLoadError("not found"))
        response = client.post("/api/plugins/nonexistent/run")
        assert response.status_code == 404

    def test_run_skill_uninit_returns_503(self, client, mock_state) -> None:
        mock_state.agent_loop = None
        response = client.post("/api/plugins/garden-writer/run")
        assert response.status_code == 503


class TestWebhookEndpoint:
    """Test POST /api/webhooks/{name}."""

    def test_webhook_triggers_plugin(self, client) -> None:
        response = client.post("/api/webhooks/telegram-input", json={"message": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert data["plugin"] == "telegram-input"

    def test_webhook_unknown_plugin_returns_404(self, client, mock_state) -> None:
        from bsage.core.exceptions import PluginLoadError

        mock_state.plugin_loader.get = MagicMock(side_effect=PluginLoadError("not found"))
        response = client.post("/api/webhooks/nonexistent", json={})
        assert response.status_code == 404

    def test_webhook_uninit_returns_503(self, client, mock_state) -> None:
        mock_state.agent_loop = None
        response = client.post("/api/webhooks/telegram-input", json={})
        assert response.status_code == 503

    def test_webhook_plugin_error_returns_500(self, client, mock_state) -> None:
        mock_state.agent_loop.on_input = AsyncMock(side_effect=RuntimeError("failed"))
        response = client.post("/api/webhooks/telegram-input", json={})
        assert response.status_code == 500

    def test_webhook_passes_raw_body_and_signature(self, client, mock_state) -> None:
        response = client.post(
            "/api/webhooks/telegram-input",
            json={"message": "hello"},
            headers={"x-hub-signature-256": "sha256=abc123"},
        )
        assert response.status_code == 200
        call_args = mock_state.agent_loop.on_input.call_args
        body = call_args[0][1]
        assert "raw_body" in body
        assert body["x-hub-signature-256"] == "sha256=abc123"
        assert body["message"] == "hello"

    def test_webhook_invalid_json_passes_empty_dict_with_raw_body(self, client, mock_state) -> None:
        response = client.post(
            "/api/webhooks/telegram-input",
            content=b"not json",
            headers={"content-type": "text/plain"},
        )
        assert response.status_code == 200
        call_args = mock_state.agent_loop.on_input.call_args
        body = call_args[0][1]
        assert body["raw_body"] == "not json"

    def test_webhook_non_dict_json_wraps_in_data_key(self, client, mock_state) -> None:
        response = client.post(
            "/api/webhooks/telegram-input",
            content=b"[1, 2, 3]",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 200
        call_args = mock_state.agent_loop.on_input.call_args
        body = call_args[0][1]
        assert body["data"] == [1, 2, 3]
        assert "raw_body" in body

    def test_webhook_invalid_utf8_returns_400(self, client, mock_state) -> None:
        response = client.post(
            "/api/webhooks/telegram-input",
            content=b"\xff\xfe invalid",
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 400


class TestActionsEndpoint:
    """Test GET /api/vault/actions."""

    def test_list_actions_returns_empty(self, client) -> None:
        response = client.get("/api/vault/actions")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_actions_returns_filenames(self, client, mock_state) -> None:
        from pathlib import Path

        mock_state.vault.read_notes = AsyncMock(
            return_value=[Path("2026-02-22.md"), Path("2026-02-21.md")]
        )
        response = client.get("/api/vault/actions")
        assert response.status_code == 200
        assert "2026-02-22.md" in response.json()


class TestConnectionManager:
    """Test WebSocket ConnectionManager."""

    async def test_connect_adds_to_connections(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        assert len(mgr._connections) == 1
        ws.accept.assert_called_once()

    async def test_disconnect_removes_from_connections(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        await mgr.disconnect(ws)
        assert len(mgr._connections) == 0

    async def test_has_connections_false_when_empty(self) -> None:
        mgr = ConnectionManager()
        assert mgr.has_connections() is False

    async def test_has_connections_true_when_connected(self) -> None:
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        assert mgr.has_connections() is True

    async def test_broadcast_sends_to_all(self) -> None:
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.broadcast({"type": "test"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()


class TestRunEntryEndpoint:
    """Test POST /api/run/{name} (unified plugin/skill runner)."""

    def test_run_entry_returns_results(self, client, mock_state) -> None:
        mock_state.agent_loop.get_entry = MagicMock(return_value=_make_meta(name="garden-writer"))
        response = client.post("/api/run/garden-writer")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "garden-writer"
        assert len(data["results"]) == 1

    def test_run_unknown_entry_returns_404(self, client, mock_state) -> None:
        mock_state.agent_loop.get_entry = MagicMock(side_effect=KeyError("not found"))
        response = client.post("/api/run/nonexistent")
        assert response.status_code == 404

    def test_run_entry_uninit_returns_503(self, client, mock_state) -> None:
        mock_state.agent_loop = None
        response = client.post("/api/run/garden-writer")
        assert response.status_code == 503

    def test_run_entry_error_returns_500(self, client, mock_state) -> None:
        mock_state.agent_loop.get_entry = MagicMock(return_value=_make_meta(name="garden-writer"))
        mock_state.agent_loop.on_input = AsyncMock(side_effect=RuntimeError("boom"))
        response = client.post("/api/run/garden-writer")
        assert response.status_code == 500


class TestAppState:
    """Test AppState initialization and lifecycle."""

    async def test_initialize_loads_skills(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
            prompts_dir=tmp_path / "prompts",
        )
        state = AppState(settings)
        await state.initialize()
        assert state.agent_loop is not None
        assert state.scheduler is not None

    async def test_event_bus_created_with_broadcaster(self, tmp_path) -> None:
        from bsage.core.events import EventBus
        from bsage.gateway.event_broadcaster import WebSocketEventBroadcaster

        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
            prompts_dir=tmp_path / "prompts",
        )
        state = AppState(settings)
        assert isinstance(state.event_bus, EventBus)
        assert isinstance(state._ws_broadcaster, WebSocketEventBroadcaster)
        assert state._ws_broadcaster in state.event_bus._subscribers

    async def test_shutdown_stops_scheduler(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
            prompts_dir=tmp_path / "prompts",
        )
        state = AppState(settings)
        await state.initialize()
        await state.shutdown()
        # Should not raise

    async def test_shutdown_without_init(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
            prompts_dir=tmp_path / "prompts",
        )
        state = AppState(settings)
        # Shutdown before init should be safe
        await state.shutdown()


class TestConfigEndpoints:
    """Test GET/PATCH /api/config."""

    def test_get_config_returns_snapshot(self, client) -> None:
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["llm_model"] == "anthropic/claude-sonnet-4-20250514"
        assert data["safe_mode"] is True
        assert "llm_api_key" not in data

    def test_patch_config_updates_model(self, client) -> None:
        response = client.patch("/api/config", json={"llm_model": "ollama/llama3"})
        assert response.status_code == 200
        data = response.json()
        assert data["llm_model"] == "ollama/llama3"

    def test_patch_config_updates_safe_mode(self, client) -> None:
        response = client.patch("/api/config", json={"safe_mode": False})
        assert response.status_code == 200
        data = response.json()
        assert data["safe_mode"] is False

    def test_patch_config_empty_model_returns_422(self, client) -> None:
        response = client.patch("/api/config", json={"llm_model": ""})
        assert response.status_code == 422

    def test_patch_config_partial_update(self, client) -> None:
        response = client.patch("/api/config", json={"safe_mode": False})
        assert response.status_code == 200
        # Model should not change
        assert response.json()["llm_model"] == "anthropic/claude-sonnet-4-20250514"


class TestSyncBackendsEndpoint:
    """Test GET /api/sync-backends."""

    def test_list_sync_backends_empty(self, client) -> None:
        response = client.get("/api/sync-backends")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_sync_backends_with_registered(self, client, mock_state) -> None:
        from unittest.mock import PropertyMock

        backend = AsyncMock()
        type(backend).name = PropertyMock(return_value="s3")
        mock_state.sync_manager.register(backend)

        response = client.get("/api/sync-backends")
        assert response.status_code == 200
        assert "s3" in response.json()


class TestCreateApp:
    """Test create_app factory."""

    def test_create_app_returns_fastapi(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
            prompts_dir=tmp_path / "prompts",
        )
        app = create_app(settings)
        assert isinstance(app, FastAPI)
        assert app.title == "BSage Gateway"


class TestChatEndpoint:
    """Test POST /api/chat."""

    def test_chat_returns_response(self, client) -> None:
        response = client.post("/api/chat", json={"message": "Hello"})
        assert response.status_code == 200
        data = response.json()
        assert "response" in data

    def test_chat_with_history(self, client) -> None:
        response = client.post(
            "/api/chat",
            json={
                "message": "Follow up",
                "history": [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello!"},
                ],
            },
        )
        assert response.status_code == 200

    def test_chat_missing_message_returns_422(self, client) -> None:
        response = client.post("/api/chat", json={})
        assert response.status_code == 422

    def test_chat_agent_loop_error_returns_500(self, client, mock_state) -> None:
        mock_state.chat_bridge.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        response = client.post("/api/chat", json={"message": "Hello"})
        assert response.status_code == 500

    def test_chat_uninit_returns_503(self, client, mock_state) -> None:
        mock_state.chat_bridge = None
        response = client.post("/api/chat", json={"message": "Hello"})
        assert response.status_code == 503


class TestCredentialFieldsEndpoint:
    """Test GET /api/entries/{name}/credentials/fields."""

    def test_plugin_with_fields(self, client, mock_state) -> None:
        meta = PluginMeta(
            name="email-input",
            version="1.0.0",
            category="input",
            description="Email",
            credentials=[
                {"name": "email", "description": "Email addr", "required": True},
                {"name": "password", "description": "Password", "required": True},
            ],
        )
        mock_state.plugin_loader.get = MagicMock(return_value=meta)

        response = client.get("/api/entries/email-input/credentials/fields")
        assert response.status_code == 200
        data = response.json()
        assert len(data["fields"]) == 2
        assert data["fields"][0]["name"] == "email"

    def test_plugin_with_setup_fn(self, client, mock_state) -> None:
        meta = PluginMeta(
            name="oauth-plugin",
            version="1.0.0",
            category="input",
            description="OAuth plugin",
            credentials=[
                {"name": "api_key", "description": "API key", "required": True},
            ],
            _setup_fn=lambda store: None,
        )
        mock_state.plugin_loader.get = MagicMock(return_value=meta)

        response = client.get("/api/entries/oauth-plugin/credentials/fields")
        assert response.status_code == 200
        data = response.json()
        assert len(data["fields"]) == 1
        assert data["fields"][0]["name"] == "api_key"

    def test_skill_with_fields(self, client, mock_state) -> None:
        from bsage.core.exceptions import PluginLoadError

        mock_state.plugin_loader.get = MagicMock(side_effect=PluginLoadError("nope"))
        meta = _make_meta(
            name="custom-skill",
            credentials={
                "fields": [
                    {"name": "token", "description": "API token", "required": True},
                ],
            },
        )
        mock_state.skill_loader.get = MagicMock(return_value=meta)

        response = client.get("/api/entries/custom-skill/credentials/fields")
        assert response.status_code == 200
        data = response.json()
        assert len(data["fields"]) == 1

    def test_skill_with_setup_entrypoint(self, client, mock_state) -> None:
        from bsage.core.exceptions import PluginLoadError

        mock_state.plugin_loader.get = MagicMock(side_effect=PluginLoadError("nope"))
        meta = _make_meta(
            name="setup-skill",
            credentials={
                "setup_entrypoint": "setup.py::run",
                "fields": [
                    {"name": "token", "description": "API token", "required": True},
                ],
            },
        )
        mock_state.skill_loader.get = MagicMock(return_value=meta)

        response = client.get("/api/entries/setup-skill/credentials/fields")
        assert response.status_code == 200
        data = response.json()
        assert len(data["fields"]) == 1
        assert data["fields"][0]["name"] == "token"

    def test_unknown_entry_returns_404(self, client, mock_state) -> None:
        from bsage.core.exceptions import PluginLoadError, SkillLoadError

        mock_state.plugin_loader.get = MagicMock(side_effect=PluginLoadError("nope"))
        mock_state.skill_loader.get = MagicMock(side_effect=SkillLoadError("nope"))

        response = client.get("/api/entries/nonexistent/credentials/fields")
        assert response.status_code == 404

    def test_entry_no_credentials(self, client, mock_state) -> None:
        meta = PluginMeta(
            name="simple-plugin",
            version="1.0.0",
            category="process",
            description="No creds",
            credentials=None,
        )
        mock_state.plugin_loader.get = MagicMock(return_value=meta)

        response = client.get("/api/entries/simple-plugin/credentials/fields")
        assert response.status_code == 200
        data = response.json()
        assert data["fields"] == []


class TestStoreCredentialsEndpoint:
    """Test POST /api/entries/{name}/credentials."""

    def test_store_credentials_success(self, client, mock_state) -> None:
        meta = PluginMeta(
            name="email-input",
            version="1.0.0",
            category="input",
            description="Email",
            credentials=[{"name": "token", "description": "Token", "required": True}],
        )
        mock_state.plugin_loader.get = MagicMock(return_value=meta)
        mock_state.credential_store.store = AsyncMock()

        response = client.post(
            "/api/entries/email-input/credentials",
            json={"credentials": {"token": "abc123"}},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_state.credential_store.store.assert_called_once_with(
            "email-input", {"token": "abc123"}
        )

    def test_store_credentials_unknown_entry_404(self, client, mock_state) -> None:
        from bsage.core.exceptions import PluginLoadError, SkillLoadError

        mock_state.plugin_loader.get = MagicMock(side_effect=PluginLoadError("nope"))
        mock_state.skill_loader.get = MagicMock(side_effect=SkillLoadError("nope"))

        response = client.post(
            "/api/entries/nonexistent/credentials",
            json={"credentials": {"x": "y"}},
        )
        assert response.status_code == 404

    def test_store_credentials_setup_fn_plugin_succeeds(self, client, mock_state) -> None:
        meta = PluginMeta(
            name="oauth-plugin",
            version="1.0.0",
            category="input",
            description="OAuth",
            credentials=[
                {"name": "api_key", "description": "API key", "required": True},
            ],
            _setup_fn=lambda store: None,
        )
        mock_state.plugin_loader.get = MagicMock(return_value=meta)
        mock_state.credential_store.store = AsyncMock()

        response = client.post(
            "/api/entries/oauth-plugin/credentials",
            json={"credentials": {"api_key": "test123"}},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_state.credential_store.store.assert_called_once_with(
            "oauth-plugin", {"api_key": "test123"}
        )


class TestToggleEndpoint:
    """Test POST /api/entries/{name}/toggle."""

    def test_toggle_disables_entry(self, client, mock_state) -> None:
        response = client.post("/api/entries/some-plugin/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "some-plugin"
        assert data["enabled"] is False

    def test_toggle_enables_disabled_entry(self, client, mock_state) -> None:
        mock_state.runtime_config.update(disabled_entries=["some-plugin"])
        response = client.post("/api/entries/some-plugin/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True

    def test_run_disabled_entry_returns_403(self, client, mock_state) -> None:
        mock_state.runtime_config.update(disabled_entries=["garden-writer"])
        mock_state.agent_loop.get_entry = MagicMock(return_value=_make_meta(name="garden-writer"))
        response = client.post("/api/run/garden-writer")
        assert response.status_code == 403

    def test_run_disabled_plugin_returns_403(self, client, mock_state) -> None:
        mock_state.runtime_config.update(disabled_entries=["garden-writer"])
        response = client.post("/api/plugins/garden-writer/run")
        assert response.status_code == 403


class TestVaultTreeEndpoint:
    """Test GET /api/vault/tree."""

    def test_vault_tree_returns_structure(self, client, mock_state, tmp_path) -> None:
        vault_root = tmp_path / "vault"
        (vault_root / "seeds").mkdir(parents=True)
        (vault_root / "garden" / "idea").mkdir(parents=True)
        (vault_root / "actions").mkdir(parents=True)
        (vault_root / "seeds" / "note.md").write_text("test")

        mock_state.vault.root = vault_root

        response = client.get("/api/vault/tree")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        paths = [e["path"] for e in data]
        assert "" in paths  # root

    def test_vault_tree_excludes_hidden_dirs(self, client, mock_state, tmp_path) -> None:
        vault_root = tmp_path / "vault"
        (vault_root / ".obsidian").mkdir(parents=True)
        (vault_root / "seeds").mkdir(parents=True)

        mock_state.vault.root = vault_root

        response = client.get("/api/vault/tree")
        data = response.json()
        all_dirs = []
        for entry in data:
            all_dirs.extend(entry["dirs"])
        assert ".obsidian" not in all_dirs


class TestVaultFileEndpoint:
    """Test GET /api/vault/file."""

    def test_vault_file_returns_content(self, client, mock_state, tmp_path) -> None:
        vault_root = tmp_path / "vault"
        (vault_root / "seeds").mkdir(parents=True)
        note = vault_root / "seeds" / "note.md"
        note.write_text("# Test Note\nContent here")

        mock_state.vault.resolve_path = MagicMock(return_value=note)
        mock_state.vault.read_note_content = AsyncMock(return_value="# Test Note\nContent here")

        response = client.get("/api/vault/file?path=seeds/note.md")
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "seeds/note.md"
        assert "Test Note" in data["content"]

    def test_vault_file_traversal_returns_400(self, client, mock_state) -> None:
        from bsage.core.exceptions import VaultPathError

        mock_state.vault.resolve_path = MagicMock(side_effect=VaultPathError("traversal blocked"))

        response = client.get("/api/vault/file?path=../../etc/passwd")
        assert response.status_code == 400

    def test_vault_file_not_found_returns_404(self, client, mock_state, tmp_path) -> None:
        resolved = tmp_path / "nonexistent.md"
        mock_state.vault.resolve_path = MagicMock(return_value=resolved)

        response = client.get("/api/vault/file?path=nonexistent.md")
        assert response.status_code == 404


class TestConfigEndpointsExtended:
    """Test config endpoints with new fields."""

    def test_get_config_includes_has_api_key(self, client) -> None:
        response = client.get("/api/config")
        data = response.json()
        assert "has_llm_api_key" in data
        assert data["has_llm_api_key"] is True  # test-key is set

    def test_get_config_includes_index_available(self, client) -> None:
        response = client.get("/api/config")
        data = response.json()
        assert "index_available" in data

    def test_get_config_includes_disabled_entries(self, client) -> None:
        response = client.get("/api/config")
        data = response.json()
        assert "disabled_entries" in data
        assert data["disabled_entries"] == []

    def test_patch_config_updates_disabled_entries(self, client) -> None:
        response = client.patch(
            "/api/config",
            json={"disabled_entries": ["plugin-a", "skill-b"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["disabled_entries"] == ["plugin-a", "skill-b"]

    def test_skills_include_enabled_field(self, client) -> None:
        response = client.get("/api/skills")
        skill = response.json()[0]
        assert "enabled" in skill
        assert skill["enabled"] is True
