"""Tests for knowledge provider API endpoints."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes


def _build_knowledge_vault(tmp_path: Path) -> Path:
    """Create a vault with notes of various types for knowledge testing."""
    vault_root = tmp_path / "vault"

    # facts/ — SOT content
    facts_dir = vault_root / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "python-typing.md").write_text(
        "---\ntype: fact\nstatus: growing\ntags:\n  - python\n  - typing\n"
        "related:\n  - '[[Project Alpha]]'\ncaptured_at: '2026-03-01'\n---\n"
        "# Python Typing Best Practices\n\nAlways use type hints.\n"
    )
    (facts_dir / "docker-compose.md").write_text(
        "---\ntype: fact\nstatus: seed\ntags:\n  - docker\n  - devops\n"
        "captured_at: '2026-03-10'\n---\n"
        "# Docker Compose Tips\n\nUse version 3 syntax.\n"
    )

    # insights/ — SOT content
    insights_dir = vault_root / "insights"
    insights_dir.mkdir(parents=True)
    (insights_dir / "weekly-digest.md").write_text(
        "---\ntype: insight\nstatus: growing\ntags:\n  - weekly\n  - review\n"
        "related:\n  - '[[Project Alpha]]'\ncaptured_at: '2026-03-15'\n---\n"
        "# Weekly Digest\n\nKey themes this week.\n"
    )

    # tasks/ — SOP content
    tasks_dir = vault_root / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "deploy-pipeline.md").write_text(
        "---\ntype: task\nstatus: seed\ntags:\n  - devops\n  - pipeline\n"
        "captured_at: '2026-03-20'\n---\n"
        "# Deploy Pipeline Setup\n\nSet up CI/CD for project.\n"
    )

    # ideas/ — NOT SOT/SOP (should be excluded from sot results)
    ideas_dir = vault_root / "ideas"
    ideas_dir.mkdir(parents=True)
    (ideas_dir / "random-thought.md").write_text(
        "---\ntype: idea\nstatus: seed\ntags:\n  - random\n"
        "captured_at: '2026-03-22'\n---\n"
        "# Random Thought\n\nSome random idea.\n"
    )

    return vault_root


@pytest.fixture()
def vault_root(tmp_path):
    return _build_knowledge_vault(tmp_path)


@pytest.fixture()
def mock_state(vault_root):
    """Create a mocked AppState with a real vault for knowledge testing."""
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
    state.embedder = MagicMock()
    state.embedder.enabled = False
    state.vector_store = MagicMock()
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="You are BSage.")
    state.prompt_registry.render = MagicMock(return_value="Chat instructions here.")
    state.chat_bridge = AsyncMock()
    state.garden_writer = AsyncMock()

    # Ontology mock — provides entity types with folders
    ontology = MagicMock()
    ontology.get_entity_types.return_value = {
        "idea": {"folder": "ideas/", "knowledge_layer": "semantic"},
        "insight": {"folder": "insights/", "knowledge_layer": "semantic"},
        "fact": {"folder": "facts/", "knowledge_layer": "semantic"},
        "task": {"folder": "tasks/", "knowledge_layer": "episodic"},
        "project": {"folder": "projects/", "knowledge_layer": "semantic"},
        "person": {"folder": "people/", "knowledge_layer": "semantic"},
        "event": {"folder": "events/", "knowledge_layer": "episodic"},
        "preference": {"folder": "preferences/", "knowledge_layer": "procedural"},
    }
    state.ontology = ontology

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


class TestKnowledgeSearchEndpoint:
    """Tests for GET /api/knowledge/search."""

    def test_search_returns_results(self, client):
        """Full-text search finds matching notes."""
        resp = client.get("/api/knowledge/search", params={"q": "type hints"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) >= 1
        result = data["results"][0]
        assert "title" in result
        assert "path" in result
        assert "content_preview" in result
        assert "relevance_score" in result
        assert "tags" in result

    def test_search_no_results(self, client):
        """Search with no matching content returns empty results."""
        resp = client.get("/api/knowledge/search", params={"q": "xyznonexistent123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    def test_search_missing_query_param(self, client):
        """Missing q param returns 422 validation error."""
        resp = client.get("/api/knowledge/search")
        assert resp.status_code == 422

    def test_search_respects_limit(self, client):
        """Limit param caps the number of results."""
        resp = client.get("/api/knowledge/search", params={"q": "type", "limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 1

    def test_search_content_preview_is_truncated(self, client):
        """Content preview should be a reasonable length, not the full note."""
        resp = client.get("/api/knowledge/search", params={"q": "Docker"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        for result in data["results"]:
            assert len(result["content_preview"]) <= 300

    def test_search_with_vector_store(self, mock_state):
        """When embedder is enabled, uses semantic search."""
        mock_embedder = MagicMock()
        mock_embedder.enabled = True
        mock_embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
        mock_state.embedder = mock_embedder

        mock_vector_store = MagicMock()
        mock_vector_store.search = AsyncMock(
            return_value=[
                ("facts/python-typing.md", 0.95),
                ("insights/weekly-digest.md", 0.80),
            ]
        )
        mock_state.vector_store = mock_vector_store

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        vector_client = TestClient(app)

        resp = vector_client.get("/api/knowledge/search", params={"q": "python typing"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["results"][0]["relevance_score"] == 0.95
        assert data["results"][0]["title"] == "Python Typing Best Practices"

    def test_search_vector_fallback_on_error(self, mock_state):
        """Falls back to full-text search when vector store errors."""
        mock_embedder = MagicMock()
        mock_embedder.enabled = True
        mock_embedder.embed = AsyncMock(side_effect=RuntimeError("embedding failed"))
        mock_state.embedder = mock_embedder
        mock_state.vector_store = MagicMock()

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        fallback_client = TestClient(app)

        resp = fallback_client.get("/api/knowledge/search", params={"q": "Docker"})
        assert resp.status_code == 200
        data = resp.json()
        # Should still return results via full-text fallback
        assert len(data["results"]) >= 1


class TestKnowledgeEntriesEndpoint:
    """Tests for POST /api/knowledge/entries."""

    def test_create_entry_success(self, client, mock_state, vault_root):
        """POST /api/knowledge/entries creates a garden note and returns path."""
        mock_writer = AsyncMock()
        created_path = vault_root / "ideas" / "my-new-note.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        # Rebuild client with updated state
        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/entries",
            json={
                "title": "My New Note",
                "content": "Some interesting content.",
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
        # Path is relative to vault root
        assert data["path"] == "ideas/my-new-note.md"

        # Verify GardenWriter was called with correct args
        mock_writer.write_garden.assert_called_once()
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.title == "My New Note"
        assert call_arg.source == "bsnexus-planner"
        # Links should be converted to wikilinks in related
        assert "Project Alpha" in call_arg.related
        assert "BSage" in call_arg.related

    def test_create_entry_minimal_fields(self, client, mock_state, vault_root):
        """Only title and content are required."""
        mock_writer = AsyncMock()
        created_path = vault_root / "ideas" / "minimal-note.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/entries",
            json={"title": "Minimal Note", "content": "Just content."},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["path"] == "ideas/minimal-note.md"

    def test_create_entry_validation_error_missing_title(self, client):
        """Missing title returns 422."""
        resp = client.post(
            "/api/knowledge/entries",
            json={"content": "No title provided."},
        )
        assert resp.status_code == 422

    def test_create_entry_validation_error_missing_content(self, client):
        """Missing content returns 422."""
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "No content"},
        )
        assert resp.status_code == 422

    def test_create_entry_with_metadata(self, client, mock_state, vault_root):
        """Metadata dict is passed as extra_fields to GardenNote."""
        mock_writer = AsyncMock()
        created_path = vault_root / "ideas" / "meta-note.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/entries",
            json={
                "title": "Note With Metadata",
                "content": "Content here.",
                "metadata": {"priority": "high", "domain": "engineering"},
                "source": "test-source",
            },
        )
        assert resp.status_code == 201

        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.extra_fields == {"priority": "high", "domain": "engineering"}

    def test_create_entry_links_become_related(self, client, mock_state, vault_root):
        """Links field is converted to related wikilinks."""
        mock_writer = AsyncMock()
        created_path = vault_root / "ideas" / "linked-note.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/entries",
            json={
                "title": "Linked Note",
                "content": "Content.",
                "links": ["Alpha", "Beta", "Gamma"],
            },
        )
        assert resp.status_code == 201

        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.related == ["Alpha", "Beta", "Gamma"]

    def test_create_entry_empty_body_returns_422(self, client):
        """Empty JSON body returns 422."""
        resp = client.post("/api/knowledge/entries", json={})
        assert resp.status_code == 422

    def test_create_entry_custom_note_type(self, client, mock_state, vault_root):
        """note_type field overrides the default 'idea' type."""
        mock_writer = AsyncMock()
        created_path = vault_root / "facts" / "custom-type-note.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/entries",
            json={
                "title": "Custom Type Note",
                "content": "A fact note.",
                "note_type": "fact",
                "source": "test",
            },
        )
        assert resp.status_code == 201
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.note_type == "fact"

    def test_create_entry_default_note_type_is_idea(self, client, mock_state, vault_root):
        """Without note_type field, default is 'idea'."""
        mock_writer = AsyncMock()
        created_path = vault_root / "ideas" / "default-type.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/entries",
            json={
                "title": "Default Type Note",
                "content": "Should be idea.",
            },
        )
        assert resp.status_code == 201
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.note_type == "idea"


class TestDecisionRecordEndpoint:
    """Tests for POST /api/knowledge/decisions."""

    def test_create_decision_success(self, client, mock_state, vault_root):
        """POST /api/knowledge/decisions creates a structured decision record."""
        mock_writer = AsyncMock()
        created_path = vault_root / "decisions" / "use-postgres.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Use PostgreSQL for persistence",
                "decision": "We will use PostgreSQL as our primary database.",
                "reasoning": "Strong ACID compliance and JSON support.",
                "alternatives": ["MongoDB", "SQLite", "DynamoDB"],
                "context": "Evaluating databases for the new service.",
                "tags": ["database", "architecture"],
                "source": "bsnexus-planner",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "path" in data
        assert "created_at" in data
        assert data["path"] == "decisions/use-postgres.md"

    def test_create_decision_template_format(self, client, mock_state, vault_root):
        """Decision content follows the structured template."""
        mock_writer = AsyncMock()
        created_path = vault_root / "decisions" / "use-rest.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Use REST over GraphQL",
                "decision": "REST API for all endpoints.",
                "reasoning": "Team familiarity and simpler tooling.",
                "alternatives": ["GraphQL", "gRPC"],
                "context": "API design for v2.",
                "tags": ["api"],
                "source": "api",
            },
        )
        assert resp.status_code == 201

        mock_writer.write_garden.assert_called_once()
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.note_type == "insight"
        assert "## Decision" in call_arg.content
        assert "## Reasoning" in call_arg.content
        assert "## Alternatives Considered" in call_arg.content
        assert "## Context" in call_arg.content
        assert "REST API for all endpoints." in call_arg.content
        assert "Team familiarity and simpler tooling." in call_arg.content
        assert "- GraphQL" in call_arg.content
        assert "- gRPC" in call_arg.content
        assert "API design for v2." in call_arg.content

    def test_create_decision_note_type_is_insight(self, client, mock_state, vault_root):
        """Decision records use note_type='insight'."""
        mock_writer = AsyncMock()
        created_path = vault_root / "decisions" / "test-decision.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Test Decision",
                "decision": "Decision text.",
                "reasoning": "Reasoning text.",
                "alternatives": [],
                "context": "Context text.",
            },
        )
        assert resp.status_code == 201
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.note_type == "insight"

    def test_create_decision_missing_title(self, client):
        """Missing title returns 422."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "decision": "Some decision.",
                "reasoning": "Some reasoning.",
            },
        )
        assert resp.status_code == 422

    def test_create_decision_missing_decision_field(self, client):
        """Missing decision field returns 422."""
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Missing Decision Field",
                "reasoning": "Some reasoning.",
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
            },
        )
        assert resp.status_code == 422

    def test_create_decision_empty_alternatives(self, client, mock_state, vault_root):
        """Empty alternatives list is valid."""
        mock_writer = AsyncMock()
        created_path = vault_root / "decisions" / "no-alts.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "No Alternatives",
                "decision": "Only option.",
                "reasoning": "No other choice.",
                "alternatives": [],
                "context": "Limited options.",
            },
        )
        assert resp.status_code == 201
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert "## Alternatives Considered" in call_arg.content

    def test_create_decision_tags_passed_through(self, client, mock_state, vault_root):
        """Tags are passed to the GardenNote."""
        mock_writer = AsyncMock()
        created_path = vault_root / "decisions" / "tagged.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Tagged Decision",
                "decision": "Decision.",
                "reasoning": "Reasoning.",
                "alternatives": [],
                "context": "",
                "tags": ["infra", "security"],
                "source": "test",
            },
        )
        assert resp.status_code == 201
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.tags == ["infra", "security"]

    def test_create_decision_custom_note_type(self, client, mock_state, vault_root):
        """note_type field overrides the default 'insight' type."""
        mock_writer = AsyncMock()
        created_path = vault_root / "facts" / "fact-decision.md"
        mock_writer.write_garden = AsyncMock(return_value=created_path)
        mock_state.garden_writer = mock_writer

        app = FastAPI()
        app.include_router(create_routes(mock_state))
        test_client = TestClient(app)

        resp = test_client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Custom Type Decision",
                "decision": "A fact-based decision.",
                "reasoning": "Based on verified data.",
                "note_type": "fact",
                "alternatives": [],
                "context": "",
                "source": "test",
            },
        )
        assert resp.status_code == 201
        call_arg = mock_writer.write_garden.call_args[0][0]
        assert call_arg.note_type == "fact"

    def test_create_decision_writer_error(self, client, mock_state):
        """GardenWriter failure returns 500."""
        mock_state.garden_writer.write_garden = AsyncMock(side_effect=OSError("Disk full"))
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Will Fail",
                "decision": "Decision.",
                "reasoning": "Reasoning.",
                "alternatives": [],
                "context": "",
            },
        )
        assert resp.status_code == 500
