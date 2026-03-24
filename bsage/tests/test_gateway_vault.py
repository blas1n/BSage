"""Tests for vault search, backlinks, graph, and tags endpoints."""

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


def _build_vault(tmp_path: Path) -> Path:
    """Create a small vault with wikilinks and tags for testing."""
    vault_root = tmp_path / "vault"

    # garden/idea/project-x.md
    idea_dir = vault_root / "garden" / "idea"
    idea_dir.mkdir(parents=True)
    (idea_dir / "project-x.md").write_text(
        "---\ntype: idea\nstatus: growing\n---\n"
        "# Project X\n\nThis is about [[weekly-digest]] and #project stuff.\n"
        "Also related to [[calendar-notes]].\n"
    )

    # garden/insight/weekly-digest.md
    insight_dir = vault_root / "garden" / "insight"
    insight_dir.mkdir(parents=True)
    (insight_dir / "weekly-digest.md").write_text(
        "---\ntype: insight\n---\n"
        "# Weekly Digest\n\nSummary of the week. See [[project-x|Project X]].\n"
        "Tags: #insight #project\n"
    )

    # seeds/telegram/2026-03-01.md
    seed_dir = vault_root / "seeds" / "telegram"
    seed_dir.mkdir(parents=True)
    (seed_dir / "2026-03-01.md").write_text(
        "---\nsource: telegram\n---\nGot a message about #todo items.\n"
    )

    # actions/2026-03-07.md (no wikilinks, no tags)
    actions_dir = vault_root / "actions"
    actions_dir.mkdir(parents=True)
    (actions_dir / "2026-03-07.md").write_text("- **10:00** | `garden-writer` | wrote 2 notes\n")

    return vault_root


@pytest.fixture()
def vault_root(tmp_path):
    return _build_vault(tmp_path)


@pytest.fixture()
def mock_state(vault_root):
    """Create a mocked AppState with a real vault directory."""
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
    state.chat_bridge = AsyncMock()
    state.chat_bridge.chat = AsyncMock(return_value="Mocked")
    state.prompt_registry = MagicMock(spec=PromptRegistry)

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


class TestVaultSearchEndpoint:
    """Test GET /api/vault/search."""

    def test_search_finds_matching_content(self, client) -> None:
        response = client.get("/api/vault/search?q=weekly")
        assert response.status_code == 200
        data = response.json()
        paths = [r["path"] for r in data]
        assert any("weekly-digest" in p for p in paths)

    def test_search_case_insensitive(self, client) -> None:
        response = client.get("/api/vault/search?q=PROJECT")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

    def test_search_returns_empty_for_no_match(self, client) -> None:
        response = client.get("/api/vault/search?q=zzz_nonexistent_zzz")
        assert response.status_code == 200
        assert response.json() == []

    def test_search_returns_line_numbers(self, client) -> None:
        response = client.get("/api/vault/search?q=Summary")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        matches = data[0]["matches"]
        assert len(matches) > 0
        assert "line" in matches[0]
        assert "text" in matches[0]

    def test_search_requires_query(self, client) -> None:
        response = client.get("/api/vault/search")
        assert response.status_code == 422


class TestVaultBacklinksEndpoint:
    """Test GET /api/vault/backlinks."""

    def test_finds_backlinks_by_stem(self, client) -> None:
        response = client.get("/api/vault/backlinks?path=garden/insight/weekly-digest.md")
        assert response.status_code == 200
        data = response.json()
        paths = [r["path"] for r in data]
        assert any("project-x" in p for p in paths)

    def test_finds_backlinks_with_alias(self, client) -> None:
        # weekly-digest.md links to [[project-x|Project X]]
        response = client.get("/api/vault/backlinks?path=garden/idea/project-x.md")
        assert response.status_code == 200
        data = response.json()
        paths = [r["path"] for r in data]
        assert any("weekly-digest" in p for p in paths)

    def test_no_backlinks_for_unlinked_note(self, client) -> None:
        response = client.get("/api/vault/backlinks?path=actions/2026-03-07.md")
        assert response.status_code == 200
        assert response.json() == []

    def test_backlink_includes_title(self, client) -> None:
        response = client.get("/api/vault/backlinks?path=garden/insight/weekly-digest.md")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert "title" in data[0]
        assert data[0]["title"] == "Project X"

    def test_self_not_included_in_backlinks(self, client) -> None:
        # project-x.md references weekly-digest, but shouldn't list itself
        response = client.get("/api/vault/backlinks?path=garden/idea/project-x.md")
        data = response.json()
        paths = [r["path"] for r in data]
        assert "garden/idea/project-x.md" not in paths


class TestVaultGraphEndpoint:
    """Test GET /api/vault/graph."""

    def test_graph_returns_nodes_and_links(self, client) -> None:
        response = client.get("/api/vault/graph")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "links" in data
        assert "truncated" in data
        assert len(data["nodes"]) == 4  # 4 .md files in our test vault
        assert data["truncated"] is False

    def test_graph_nodes_have_required_fields(self, client) -> None:
        response = client.get("/api/vault/graph")
        data = response.json()
        for node in data["nodes"]:
            assert "id" in node
            assert "name" in node
            assert "group" in node

    def test_graph_has_correct_groups(self, client) -> None:
        response = client.get("/api/vault/graph")
        data = response.json()
        groups = {n["group"] for n in data["nodes"]}
        assert "garden" in groups
        assert "seeds" in groups
        assert "actions" in groups

    def test_graph_has_links(self, client) -> None:
        response = client.get("/api/vault/graph")
        data = response.json()
        assert len(data["links"]) > 0
        for link in data["links"]:
            assert "source" in link
            assert "target" in link

    def test_graph_empty_vault(self, client, mock_state, tmp_path) -> None:
        empty_vault = tmp_path / "empty_vault"
        empty_vault.mkdir()
        mock_state.vault.root = empty_vault

        response = client.get("/api/vault/graph")
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == []
        assert data["links"] == []
        assert data["truncated"] is False

    def test_graph_max_files_truncation(self, client) -> None:
        """max_files=1 on a vault with 4 files should set truncated=True."""
        response = client.get("/api/vault/graph?max_files=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 1
        assert data["truncated"] is True

    def test_graph_max_files_no_truncation(self, client) -> None:
        """max_files larger than vault size should set truncated=False."""
        response = client.get("/api/vault/graph?max_files=2000")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is False


class TestVaultTagsEndpoint:
    """Test GET /api/vault/tags."""

    def test_tags_extracted_from_body(self, client) -> None:
        response = client.get("/api/vault/tags")
        assert response.status_code == 200
        data = response.json()
        assert "truncated" in data
        assert data["truncated"] is False
        tags = data["tags"]
        assert "project" in tags
        assert "insight" in tags
        assert "todo" in tags

    def test_tags_include_file_paths(self, client) -> None:
        response = client.get("/api/vault/tags")
        data = response.json()
        # #project appears in both project-x.md and weekly-digest.md
        project_files = data["tags"]["project"]
        assert len(project_files) == 2

    def test_tags_skip_frontmatter(self, client, mock_state, tmp_path) -> None:
        """Ensure tags inside YAML frontmatter are not extracted."""
        vault_root = tmp_path / "tag_vault"
        vault_root.mkdir()
        (vault_root / "test.md").write_text(
            "---\ntags: [#notag]\nstatus: #ignoreme\n---\nBody text with #realtag here.\n"
        )
        mock_state.vault.root = vault_root

        response = client.get("/api/vault/tags")
        data = response.json()
        tags = data["tags"]
        assert "realtag" in tags
        assert "notag" not in tags
        assert "ignoreme" not in tags

    def test_tags_empty_vault(self, client, mock_state, tmp_path) -> None:
        empty_vault = tmp_path / "empty_vault"
        empty_vault.mkdir()
        mock_state.vault.root = empty_vault

        response = client.get("/api/vault/tags")
        assert response.status_code == 200
        data = response.json()
        assert data["tags"] == {}
        assert data["truncated"] is False

    def test_tags_max_files_truncation(self, client) -> None:
        """max_files=1 on a vault with 4 files should set truncated=True."""
        response = client.get("/api/vault/tags?max_files=1")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is True

    def test_tags_max_files_no_truncation(self, client) -> None:
        """max_files larger than vault size should set truncated=False."""
        response = client.get("/api/vault/tags?max_files=2000")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is False
