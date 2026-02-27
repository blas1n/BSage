"""Tests for bsage.gateway — FastAPI Gateway routes and lifecycle."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.config import Settings
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.core.skill_loader import SkillMeta
from bsage.garden.sync import SyncManager
from bsage.gateway.app import create_app
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import ConnectionManager


def _make_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "process",
        "description": "Test skill",
    }
    defaults.update(overrides)
    return SkillMeta(**defaults)


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
        mgr.disconnect(ws)
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
        mock_state.agent_loop.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
        response = client.post("/api/chat", json={"message": "Hello"})
        assert response.status_code == 500

    def test_chat_uninit_returns_503(self, client, mock_state) -> None:
        mock_state.agent_loop = None
        response = client.post("/api/chat", json={"message": "Hello"})
        assert response.status_code == 503
