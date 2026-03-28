"""Tests for decision record API — POST /api/knowledge/decisions endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes


@pytest.fixture()
def vault_root(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture()
def mock_state(vault_root):
    """Create a mocked AppState for decision endpoint testing."""
    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.agent_loop = MagicMock()
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
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="You are BSage.")
    state.prompt_registry.render = MagicMock(return_value="Chat instructions here.")
    state.chat_bridge = AsyncMock()
    state.vector_store = None
    state.embedder = MagicMock()
    state.embedder.enabled = False

    # Mock garden_writer to return a path in decisions/ subfolder
    written_path = vault_root / "insights" / "decisions" / "test-decision.md"
    state.garden_writer = AsyncMock()
    state.garden_writer.write_garden = AsyncMock(return_value=written_path)

    async def _mock_get_current_user():
        return MagicMock(id="test-user", email="test@example.com", role="authenticated")

    state.get_current_user = _mock_get_current_user
    state.auth_provider = None
    return state


@pytest.fixture()
def client(mock_state):
    app = FastAPI()
    app.include_router(create_routes(mock_state))
    return TestClient(app)


class TestDecisionRecordEndpoint:
    """Tests for POST /api/knowledge/decisions."""

    def test_create_decision_success(self, client, mock_state):
        """Valid request creates a decision record and returns path."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Use PostgreSQL over MongoDB",
                "decision": "We chose PostgreSQL as the primary database.",
                "reasoning": "Better ACID compliance and relational query support.",
                "alternatives": ["MongoDB", "DynamoDB", "CockroachDB"],
                "context": "Building a financial transaction system.",
                "tags": ["database", "architecture"],
                "source": "bsnexus-planner",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "path" in data
        assert "created_at" in data

        # Verify GardenWriter was called
        mock_state.garden_writer.write_garden.assert_called_once()

    def test_create_decision_note_type_is_insight(self, client, mock_state):
        """Decision records are created with note_type='insight'."""
        client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Choose FastAPI",
                "decision": "Use FastAPI for the gateway.",
                "reasoning": "Async support and auto-docs.",
                "alternatives": ["Flask", "Django"],
                "context": "Need async HTTP framework.",
                "tags": [],
                "source": "test",
            },
        )
        call_arg = mock_state.garden_writer.write_garden.call_args[0][0]
        assert call_arg.note_type == "insight"

    def test_create_decision_template_format(self, client, mock_state):
        """Content follows the structured template with ## sections."""
        client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Adopt TDD",
                "decision": "All new code must have tests first.",
                "reasoning": "Reduces regression bugs significantly.",
                "alternatives": ["Write tests after", "No tests"],
                "context": "Team experiencing frequent regressions.",
                "tags": ["process"],
                "source": "test",
            },
        )
        call_arg = mock_state.garden_writer.write_garden.call_args[0][0]
        content = call_arg.content

        assert "## Decision" in content
        assert "All new code must have tests first." in content
        assert "## Reasoning" in content
        assert "Reduces regression bugs significantly." in content
        assert "## Alternatives Considered" in content
        assert "- Write tests after" in content
        assert "- No tests" in content
        assert "## Context" in content
        assert "Team experiencing frequent regressions." in content

    def test_create_decision_tags_passed_through(self, client, mock_state):
        """Tags are passed to the GardenNote."""
        client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Use structlog",
                "decision": "Adopt structlog for logging.",
                "reasoning": "Structured JSON output.",
                "alternatives": ["logging module"],
                "context": "Need better observability.",
                "tags": ["logging", "observability"],
                "source": "test",
            },
        )
        call_arg = mock_state.garden_writer.write_garden.call_args[0][0]
        assert "logging" in call_arg.tags
        assert "observability" in call_arg.tags

    def test_create_decision_missing_title(self, client):
        """Missing title returns 422."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "decision": "Some decision.",
                "reasoning": "Some reason.",
                "alternatives": [],
                "context": "Some context.",
            },
        )
        assert resp.status_code == 422

    def test_create_decision_missing_decision(self, client):
        """Missing decision field returns 422."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Missing Decision Field",
                "reasoning": "Some reason.",
                "alternatives": [],
                "context": "Some context.",
            },
        )
        assert resp.status_code == 422

    def test_create_decision_missing_reasoning(self, client):
        """Missing reasoning field returns 422."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Missing Reasoning",
                "decision": "Some decision.",
                "alternatives": [],
                "context": "Some context.",
            },
        )
        assert resp.status_code == 422

    def test_create_decision_empty_alternatives(self, client, mock_state):
        """Empty alternatives list is valid."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "No Alternatives",
                "decision": "Only option available.",
                "reasoning": "No other choices.",
                "alternatives": [],
                "context": "Constrained environment.",
                "tags": [],
                "source": "test",
            },
        )
        assert resp.status_code == 201

    def test_create_decision_default_source(self, client, mock_state):
        """Source defaults to 'api' when not provided."""
        client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Default Source",
                "decision": "Test default.",
                "reasoning": "Testing defaults.",
                "alternatives": [],
                "context": "Test context.",
            },
        )
        call_arg = mock_state.garden_writer.write_garden.call_args[0][0]
        assert call_arg.source == "api"

    def test_create_decision_writer_error(self, client, mock_state):
        """GardenWriter failure returns 500."""
        mock_state.garden_writer.write_garden = AsyncMock(side_effect=OSError("Disk full"))
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Will Fail",
                "decision": "This should error.",
                "reasoning": "Testing error handling.",
                "alternatives": [],
                "context": "Error test.",
                "source": "test",
            },
        )
        assert resp.status_code == 500

    def test_create_decision_empty_body_returns_422(self, client):
        """Empty JSON body returns 422."""
        resp = client.post("/api/knowledge/decisions", json={})
        assert resp.status_code == 422

    def test_create_decision_all_fields(self, client, mock_state):
        """Full request with all fields succeeds."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Full Decision Record",
                "decision": "Complete decision text.",
                "reasoning": "Complete reasoning text.",
                "alternatives": ["Alt A", "Alt B", "Alt C"],
                "context": "Complete context text.",
                "tags": ["arch", "infra"],
                "source": "bsnexus-planner",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"]
        assert data["path"]
        assert data["created_at"]
