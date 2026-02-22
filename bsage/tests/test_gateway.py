"""Tests for bsage.gateway — FastAPI Gateway routes and lifecycle."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.config import Settings
from bsage.core.skill_loader import SkillMeta
from bsage.gateway.app import create_app
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes
from bsage.gateway.ws import ConnectionManager


def _make_meta(**overrides) -> SkillMeta:
    defaults = {
        "name": "test-skill",
        "version": "1.0.0",
        "category": "process",
        "is_dangerous": False,
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
    state.agent_loop = MagicMock()
    state.agent_loop.on_input = AsyncMock(return_value=[{"status": "ok"}])
    state.vault = MagicMock()
    state.vault.read_notes = MagicMock(return_value=[])
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
    """Test POST /api/skills/{name}/run."""

    def test_run_skill_returns_results(self, client) -> None:
        response = client.post("/api/skills/garden-writer/run")
        assert response.status_code == 200
        data = response.json()
        assert data["skill"] == "garden-writer"
        assert len(data["results"]) == 1

    def test_run_unknown_skill_returns_404(self, client, mock_state) -> None:
        from bsage.core.exceptions import SkillLoadError

        mock_state.skill_loader.get = MagicMock(side_effect=SkillLoadError("not found"))
        response = client.post("/api/skills/nonexistent/run")
        assert response.status_code == 404

    def test_run_skill_uninit_returns_503(self, client, mock_state) -> None:
        mock_state.agent_loop = None
        response = client.post("/api/skills/garden-writer/run")
        assert response.status_code == 503


class TestActionsEndpoint:
    """Test GET /api/vault/actions."""

    def test_list_actions_returns_empty(self, client) -> None:
        response = client.get("/api/vault/actions")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_actions_returns_filenames(self, client, mock_state) -> None:
        from pathlib import Path

        mock_state.vault.read_notes = MagicMock(
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

    async def test_broadcast_sends_to_all(self) -> None:
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.broadcast({"type": "test"})
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()


class TestAppState:
    """Test AppState initialization and lifecycle."""

    async def test_initialize_loads_skills(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
        )
        state = AppState(settings)
        await state.initialize()
        assert state.agent_loop is not None
        assert state.scheduler is not None

    async def test_shutdown_stops_scheduler(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
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
        )
        state = AppState(settings)
        # Shutdown before init should be safe
        await state.shutdown()


class TestCreateApp:
    """Test create_app factory."""

    def test_create_app_returns_fastapi(self, tmp_path) -> None:
        settings = Settings(
            vault_path=tmp_path / "vault",
            skills_dir=tmp_path / "skills",
            tmp_dir=tmp_path / "tmp",
            credentials_dir=tmp_path / "creds",
        )
        app = create_app(settings)
        assert isinstance(app, FastAPI)
        assert app.title == "BSage Gateway"
