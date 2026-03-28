"""Tests for knowledge write API — POST /api/knowledge/entries endpoint."""

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
    """Create a mocked AppState with a real garden_writer mock."""
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
    state.retriever._vector_store = None
    state.retriever._embedder = None
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="You are BSage.")
    state.prompt_registry.render = MagicMock(return_value="Chat instructions here.")
    state.chat_bridge = AsyncMock()
    state.vector_store = None
    state.embedder = MagicMock()
    state.embedder.enabled = False

    # Mock garden_writer.write_garden to return a path
    written_path = vault_root / "ideas" / "test-note.md"
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


class TestKnowledgeEntriesEndpoint:
    """Tests for POST /api/knowledge/entries."""

    def test_create_entry_success(self, client, mock_state):
        """Valid request creates a garden note and returns path."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Test Note",
                "content": "Some content here.",
                "tags": ["python", "testing"],
                "links": ["Project Alpha", "BSage"],
                "source": "bsnexus-planner",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "path" in data
        assert "created_at" in data
        mock_state.garden_writer.write_garden.assert_called_once()

    def test_create_entry_generates_wikilinks(self, client, mock_state):
        """Links field is converted to wikilink format in the note content."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Linked Note",
                "content": "Original content.",
                "tags": [],
                "links": ["Project Alpha", "BSage"],
                "source": "test",
            },
        )
        assert resp.status_code == 201
        call_args = mock_state.garden_writer.write_garden.call_args
        note = call_args[0][0] if call_args[0] else call_args[1].get("note")
        # The note's related field should contain wikilinks
        if hasattr(note, "related"):
            assert "Project Alpha" in note.related
            assert "BSage" in note.related
        else:
            # If passed as dict
            assert "Project Alpha" in note.get("related", [])
            assert "BSage" in note.get("related", [])

    def test_create_entry_missing_title(self, client):
        """Missing title returns 422."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "content": "No title provided.",
                "source": "test",
            },
        )
        assert resp.status_code == 422

    def test_create_entry_missing_content(self, client):
        """Missing content returns 422."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "No Content",
                "source": "test",
            },
        )
        assert resp.status_code == 422

    def test_create_entry_minimal_fields(self, client, mock_state):
        """Only required fields (title, content, source) succeed."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Minimal Note",
                "content": "Just the basics.",
                "source": "test",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["path"]

    def test_create_entry_with_metadata(self, client, mock_state):
        """metadata dict is passed through as extra_fields."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "With Metadata",
                "content": "Has extra fields.",
                "source": "test",
                "metadata": {"priority": "high", "domain": "engineering"},
            },
        )
        assert resp.status_code == 201

    def test_create_entry_empty_links(self, client, mock_state):
        """Empty links list works fine."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "No Links",
                "content": "No related notes.",
                "tags": ["solo"],
                "links": [],
                "source": "test",
            },
        )
        assert resp.status_code == 201

    def test_create_entry_writer_error(self, client, mock_state):
        """GardenWriter failure returns 500."""
        mock_state.garden_writer.write_garden = AsyncMock(side_effect=OSError("Disk full"))
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Will Fail",
                "content": "Should error.",
                "source": "test",
            },
        )
        assert resp.status_code == 500

    def test_create_entry_wikilinks_in_content(self, client, mock_state):
        """Links are appended as wikilinks section in content."""
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "Linked Content",
                "content": "Main content.",
                "links": ["Note A", "Note B"],
                "source": "test",
            },
        )
        assert resp.status_code == 201
        call_args = mock_state.garden_writer.write_garden.call_args
        note = call_args[0][0] if call_args[0] else call_args[1].get("note")
        # Content should include wikilinks
        content = note.content if hasattr(note, "content") else note.get("content", "")
        assert "[[Note A]]" in content
        assert "[[Note B]]" in content
