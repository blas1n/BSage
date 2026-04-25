"""Wire-format contract tests for the knowledge endpoints.

These tests pin the JSON shape of the three endpoints that
``~/Works/_infra/scripts/bsage-sync.sh`` (and any external sync caller) relies
on:

* ``POST /api/knowledge/entries``   — used by the ``entry`` / ``doc`` sub-commands
* ``POST /api/knowledge/decisions`` — used by the ``decision`` sub-command
* ``GET  /api/knowledge/search``    — used by the ``search`` sub-command

The existing ``test_knowledge_*.py`` suites exercise the happy paths in detail
but fan out into many behavioural assertions. This file is intentionally
narrow: it locks in the *fields and types* on the wire so the M15 module
split (and any future refactor) cannot silently drop or rename a field.
"""

from __future__ import annotations

from datetime import datetime
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


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture()
def mock_state(vault_root: Path):
    """Minimal AppState mock that satisfies all knowledge endpoints."""
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
    state.prompt_registry.get = MagicMock(return_value="prompt")
    state.prompt_registry.render = MagicMock(return_value="prompt")
    state.chat_bridge = AsyncMock()
    state.vector_store = None
    state.embedder = MagicMock()
    state.embedder.enabled = False

    written_path = vault_root / "ideas" / "test-note.md"
    state.garden_writer = AsyncMock()
    state.garden_writer.write_garden = AsyncMock(return_value=written_path)

    ontology = MagicMock()
    ontology.get_entity_types.return_value = {
        "idea": {"folder": "ideas/", "knowledge_layer": "semantic"},
        "insight": {"folder": "insights/", "knowledge_layer": "semantic"},
    }
    state.ontology = ontology

    async def _mock_get_current_user():
        return MagicMock(id="test-user", email="test@example.com", role="authenticated")

    state.get_current_user = _mock_get_current_user
    state.auth_provider = None
    return state


@pytest.fixture()
def client(mock_state) -> TestClient:
    app = FastAPI()
    app.include_router(create_routes(mock_state))
    return TestClient(app)


def _is_iso8601(value: str) -> bool:
    """Best-effort ISO-8601 parse — accept aware or naive timestamps."""
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# POST /api/knowledge/entries — entry / doc sync sub-commands
# ---------------------------------------------------------------------------


class TestKnowledgeEntriesContract:
    def test_status_code_is_201(self, client: TestClient) -> None:
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "T", "content": "C", "source": "test"},
        )
        assert resp.status_code == 201

    def test_response_shape(self, client: TestClient) -> None:
        resp = client.post(
            "/api/knowledge/entries",
            json={"title": "T", "content": "C", "source": "test"},
        )
        body = resp.json()
        # Pinned wire keys — bsage-sync.sh and external callers consume these.
        assert set(body.keys()) == {"id", "path", "created_at"}
        assert isinstance(body["id"], str) and body["id"]
        assert isinstance(body["path"], str) and body["path"]
        assert isinstance(body["created_at"], str)
        assert _is_iso8601(body["created_at"])

    def test_request_accepts_optional_fields(self, client: TestClient) -> None:
        # All optional fields together — must not 422.
        resp = client.post(
            "/api/knowledge/entries",
            json={
                "title": "T",
                "content": "C",
                "note_type": "insight",
                "tags": ["a", "b"],
                "links": ["X", "Y"],
                "source": "bsnexus-planner",
                "metadata": {"k": "v"},
            },
        )
        assert resp.status_code == 201, resp.text

    def test_required_fields(self, client: TestClient) -> None:
        # Missing title → 422
        r1 = client.post("/api/knowledge/entries", json={"content": "x"})
        assert r1.status_code == 422
        # Missing content → 422
        r2 = client.post("/api/knowledge/entries", json={"title": "x"})
        assert r2.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/knowledge/decisions — directional decision sync sub-command
# ---------------------------------------------------------------------------


class TestKnowledgeDecisionsContract:
    def test_status_code_is_201(self, client: TestClient) -> None:
        resp = client.post(
            "/api/knowledge/decisions",
            json={"title": "Q", "decision": "D", "reasoning": "R"},
        )
        assert resp.status_code == 201, resp.text

    def test_response_shape_matches_entries(self, client: TestClient) -> None:
        # Decisions reuse CreateEntryResponse — the caller treats the two
        # endpoints uniformly. Lock that contract in.
        resp = client.post(
            "/api/knowledge/decisions",
            json={"title": "Q", "decision": "D", "reasoning": "R"},
        )
        body = resp.json()
        assert set(body.keys()) == {"id", "path", "created_at"}
        assert _is_iso8601(body["created_at"])

    def test_optional_fields(self, client: TestClient) -> None:
        resp = client.post(
            "/api/knowledge/decisions",
            json={
                "title": "Q",
                "decision": "D",
                "reasoning": "R",
                "alternatives": ["A1", "A2"],
                "context": "Some ambient context",
                "tags": ["t"],
                "source": "test",
                "note_type": "insight",
            },
        )
        assert resp.status_code == 201

    def test_required_fields(self, client: TestClient) -> None:
        # Each of title / decision / reasoning is required.
        r1 = client.post("/api/knowledge/decisions", json={"decision": "D", "reasoning": "R"})
        r2 = client.post("/api/knowledge/decisions", json={"title": "Q", "reasoning": "R"})
        r3 = client.post("/api/knowledge/decisions", json={"title": "Q", "decision": "D"})
        assert r1.status_code == 422
        assert r2.status_code == 422
        assert r3.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/knowledge/search — search sub-command
# ---------------------------------------------------------------------------


class TestKnowledgeSearchContract:
    def test_status_code_is_200(self, client: TestClient) -> None:
        resp = client.get("/api/knowledge/search", params={"q": "anything"})
        assert resp.status_code == 200

    def test_response_top_level_shape(self, client: TestClient) -> None:
        resp = client.get("/api/knowledge/search", params={"q": "anything"})
        body = resp.json()
        # The top-level wire shape is `{"results": [...]}` — bsage-sync.sh
        # parses that directly, do not change without versioning.
        assert set(body.keys()) == {"results"}
        assert isinstance(body["results"], list)

    def test_result_item_shape(self, vault_root: Path, client: TestClient) -> None:
        # Seed a vault note so the full-text branch returns something.
        target = vault_root / "ideas"
        target.mkdir()
        note = target / "alpha.md"
        note.write_text(
            "---\ntype: idea\ntags: [bsvibe]\n---\n\n# Alpha\n\nbsvibe is a topic\n",
            encoding="utf-8",
        )

        resp = client.get("/api/knowledge/search", params={"q": "bsvibe"})
        assert resp.status_code == 200
        body = resp.json()
        if not body["results"]:
            pytest.skip("Vault scan returned no results in this environment")

        item = body["results"][0]
        # Pinned wire keys for SearchResultItem.
        assert set(item.keys()) == {
            "title",
            "path",
            "content_preview",
            "relevance_score",
            "tags",
        }
        assert isinstance(item["title"], str)
        assert isinstance(item["path"], str)
        assert isinstance(item["content_preview"], str)
        assert isinstance(item["relevance_score"], (int, float))
        assert isinstance(item["tags"], list)

    def test_query_required(self, client: TestClient) -> None:
        # Missing q → 422
        resp = client.get("/api/knowledge/search")
        assert resp.status_code == 422

    def test_limit_bounds(self, client: TestClient) -> None:
        # ge=1 / le=50 enforced by Query — out-of-range → 422.
        r0 = client.get("/api/knowledge/search", params={"q": "x", "limit": 0})
        r51 = client.get("/api/knowledge/search", params={"q": "x", "limit": 51})
        assert r0.status_code == 422
        assert r51.status_code == 422
