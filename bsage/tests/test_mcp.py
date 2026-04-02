"""Tests for bsage.gateway.mcp — MCP tool endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.runtime_config import RuntimeConfig
from bsage.gateway.dependencies import AppState
from bsage.gateway.mcp import (
    _extract_body_preview,
    _meta_to_plugin_info,
    create_mcp_routes,
)
from bsage.tests.conftest import make_plugin_meta, make_skill_meta


@pytest.fixture()
def mock_state() -> MagicMock:
    """Create a mocked AppState for MCP route testing."""
    state = MagicMock(spec=AppState)

    # Auth — bypass
    async def _mock_get_current_user():
        return MagicMock(id="test-user")

    state.get_current_user = _mock_get_current_user

    # Vault
    state.vault = MagicMock()
    state.vault.resolve_path = MagicMock(side_effect=lambda p: f"/vault/{p}")
    state.vault.read_note_content = AsyncMock(return_value="---\ntags: [test]\n---\n# Note\nBody")

    # Embedder (disabled by default)
    state.embedder = MagicMock()
    state.embedder.enabled = False
    state.vector_store = None

    # Retriever
    state.retriever = MagicMock()
    state.retriever.search = AsyncMock(return_value="Found 2 notes matching query")

    # Graph retriever
    state.graph_retriever = MagicMock()
    state.graph_retriever.retrieve = AsyncMock(
        return_value="## Graph Context\nEntity: **Python** (language)"
    )

    # Agent loop
    state.agent_loop = MagicMock()
    state.agent_loop.on_input = AsyncMock(return_value=[{"status": "ok"}])
    state.agent_loop.get_entry = MagicMock(return_value=make_skill_meta(name="test-skill"))

    # Loaders
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(
        return_value={"my-plugin": make_plugin_meta(name="my-plugin", category="input")}
    )
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(
        return_value={"my-skill": make_skill_meta(name="my-skill")}
    )

    # Runtime config
    state.runtime_config = RuntimeConfig(
        llm_model="test-model",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )

    # Credential store
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])

    return state


@pytest.fixture()
def mcp_app(mock_state: MagicMock) -> FastAPI:
    """Create a test FastAPI app with MCP routes."""
    app = FastAPI()
    app.include_router(create_mcp_routes(mock_state))
    return app


@pytest.fixture()
def client(mcp_app: FastAPI) -> TestClient:
    return TestClient(mcp_app)


class TestSearchKnowledge:
    """Tests for POST /api/mcp/search_knowledge."""

    def test_search_returns_results_via_retriever(
        self, client: TestClient, mock_state: MagicMock
    ) -> None:
        resp = client.post(
            "/api/mcp/search_knowledge",
            json={"query": "python programming", "top_k": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "python programming"
        assert len(data["results"]) >= 1

    def test_search_with_vector_store(self, mock_state: MagicMock) -> None:
        mock_state.embedder.enabled = True
        mock_state.vector_store = MagicMock()
        mock_state.vector_store.search = AsyncMock(return_value=[("garden/idea/test.md", 0.95)])
        mock_state.embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        app = FastAPI()
        app.include_router(create_mcp_routes(mock_state))
        client = TestClient(app)

        resp = client.post(
            "/api/mcp/search_knowledge",
            json={"query": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["score"] == 0.95

    def test_search_validates_empty_query(self, client: TestClient) -> None:
        resp = client.post(
            "/api/mcp/search_knowledge",
            json={"query": ""},
        )
        assert resp.status_code == 422

    def test_search_vector_fallback_on_error(self, mock_state: MagicMock) -> None:
        mock_state.embedder.enabled = True
        mock_state.vector_store = MagicMock()
        mock_state.vector_store.search = AsyncMock(side_effect=RuntimeError("embed failed"))
        mock_state.embedder.embed = AsyncMock(side_effect=RuntimeError("embed failed"))

        app = FastAPI()
        app.include_router(create_mcp_routes(mock_state))
        client = TestClient(app)

        resp = client.post(
            "/api/mcp/search_knowledge",
            json={"query": "test"},
        )
        assert resp.status_code == 200
        # Falls back to retriever
        assert len(resp.json()["results"]) >= 1


class TestGetGraphContext:
    """Tests for POST /api/mcp/get_graph_context."""

    def test_returns_graph_context(self, client: TestClient) -> None:
        resp = client.post(
            "/api/mcp/get_graph_context",
            json={"topic": "Python", "max_hops": 2, "top_k": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Python"
        assert data["has_results"] is True
        assert "Graph Context" in data["context"]

    def test_returns_no_results_message(self, client: TestClient, mock_state: MagicMock) -> None:
        mock_state.graph_retriever.retrieve = AsyncMock(return_value="")
        resp = client.post(
            "/api/mcp/get_graph_context",
            json={"topic": "nonexistent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_results"] is False
        assert "No graph context found" in data["context"]

    def test_503_when_graph_unavailable(self, mock_state: MagicMock) -> None:
        mock_state.graph_retriever = None
        app = FastAPI()
        app.include_router(create_mcp_routes(mock_state))
        client = TestClient(app)
        resp = client.post(
            "/api/mcp/get_graph_context",
            json={"topic": "test"},
        )
        assert resp.status_code == 503

    def test_500_on_graph_error(self, client: TestClient, mock_state: MagicMock) -> None:
        mock_state.graph_retriever.retrieve = AsyncMock(side_effect=RuntimeError("db error"))
        resp = client.post(
            "/api/mcp/get_graph_context",
            json={"topic": "fail"},
        )
        assert resp.status_code == 500


class TestRunSkill:
    """Tests for POST /api/mcp/run_skill."""

    def test_runs_skill_successfully(self, client: TestClient) -> None:
        resp = client.post(
            "/api/mcp/run_skill",
            json={"skill_name": "test-skill", "params": {"key": "value"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["skill_name"] == "test-skill"
        assert data["success"] is True

    def test_404_for_unknown_skill(self, client: TestClient, mock_state: MagicMock) -> None:
        mock_state.agent_loop.get_entry = MagicMock(side_effect=KeyError("nope"))
        resp = client.post(
            "/api/mcp/run_skill",
            json={"skill_name": "unknown"},
        )
        assert resp.status_code == 404

    def test_403_for_disabled_skill(self, mock_state: MagicMock) -> None:
        mock_state.runtime_config.update(disabled_entries=["test-skill"])
        app = FastAPI()
        app.include_router(create_mcp_routes(mock_state))
        client = TestClient(app)
        resp = client.post(
            "/api/mcp/run_skill",
            json={"skill_name": "test-skill"},
        )
        assert resp.status_code == 403

    def test_503_when_gateway_not_initialized(self, mock_state: MagicMock) -> None:
        mock_state.agent_loop = None
        app = FastAPI()
        app.include_router(create_mcp_routes(mock_state))
        client = TestClient(app)
        resp = client.post(
            "/api/mcp/run_skill",
            json={"skill_name": "test-skill"},
        )
        assert resp.status_code == 503

    def test_execution_error_returns_failure(
        self, client: TestClient, mock_state: MagicMock
    ) -> None:
        mock_state.agent_loop.on_input = AsyncMock(side_effect=RuntimeError("exec failed"))
        resp = client.post(
            "/api/mcp/run_skill",
            json={"skill_name": "test-skill"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["results"] == "Execution failed"


class TestListPlugins:
    """Tests for GET /api/mcp/list_plugins."""

    def test_lists_all_entries(self, client: TestClient) -> None:
        resp = client.get("/api/mcp/list_plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        names = {e["name"] for e in data["entries"]}
        assert names == {"my-plugin", "my-skill"}

    def test_includes_kind_field(self, client: TestClient) -> None:
        resp = client.get("/api/mcp/list_plugins")
        entries = resp.json()["entries"]
        kinds = {e["name"]: e["kind"] for e in entries}
        assert kinds["my-plugin"] == "plugin"
        assert kinds["my-skill"] == "skill"


class TestHelpers:
    """Tests for helper functions."""

    def test_extract_body_preview_with_frontmatter(self) -> None:
        content = "---\ntags: [a]\n---\n# Title\nBody text here"
        assert _extract_body_preview(content) == "# Title\nBody text here"

    def test_extract_body_preview_without_frontmatter(self) -> None:
        content = "Just plain text"
        assert _extract_body_preview(content) == "Just plain text"

    def test_extract_body_preview_truncates(self) -> None:
        content = "a" * 500
        assert len(_extract_body_preview(content, max_len=100)) == 100

    def test_meta_to_plugin_info_plugin(self) -> None:
        meta = make_plugin_meta(name="test-p", credentials=[{"name": "token"}])
        info = _meta_to_plugin_info(meta, "plugin", ["test-p"], [])
        assert info.name == "test-p"
        assert info.kind == "plugin"
        assert info.has_credentials is True
        assert info.credentials_configured is True
        assert info.enabled is True

    def test_meta_to_plugin_info_disabled(self) -> None:
        meta = make_skill_meta(name="test-s")
        info = _meta_to_plugin_info(meta, "skill", [], ["test-s"])
        assert info.enabled is False

    def test_meta_to_plugin_info_unconfigured_creds(self) -> None:
        meta = make_plugin_meta(name="needs-setup", credentials=[{"name": "key"}])
        info = _meta_to_plugin_info(meta, "plugin", [], [])
        assert info.has_credentials is True
        assert info.credentials_configured is False
        assert info.enabled is False
