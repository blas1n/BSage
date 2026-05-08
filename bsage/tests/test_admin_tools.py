"""Tests for the first-class admin MCP tools (Phase 7 / TASK-004).

Each ``bsage <subapp>`` Typer sub-app gets a matching ``bsage_<subapp>_<action>``
first-class :class:`bsage.mcp.api.Tool`. Tests cover:

* the full admin catalog is registered (ListTools includes every name);
* one CallTool round-trip per sub-app, with a duck-typed bootstrap-style
  principal (``scope`` carries the REST scope), confirms the handler
  reaches the same service-layer call the REST route uses.

The tests stay in-process (memory ``mcp-python-sdk-testing``) — no
subprocesses, no FastAPI app spin-up.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.mcp.admin_tools import ADMIN_TOOL_NAMES, register_admin_tools
from bsage.mcp.api import ToolContext, ToolError, ToolRegistry, ToolScopeDenied
from bsage.tests.conftest import make_plugin_meta, make_skill_meta


# ---------------------------------------------------------------------------
# Fake principal — duck-typed to bsvibe_authz.User.
# ---------------------------------------------------------------------------
class _FakeUser:
    def __init__(self, *, id: str = "admin", scope: list[str] | None = None) -> None:  # noqa: A002
        self.id = id
        self.scope = scope or []
        self.email = None
        self.is_service = False
        self.active_tenant_id = None


def _full_admin_user() -> _FakeUser:
    """Principal with every scope every admin tool requires."""
    return _FakeUser(
        scope=[
            "bsage.plugins.read",
            "bsage.plugins.execute",
            "bsage.plugins.install",
            "bsage.config.read",
            "bsage.config.write",
            "bsage.vault.read",
            "bsage.canonicalization.read",
            "bsage.canonicalization.draft",
            "bsage.canonicalization.apply",
        ],
    )


# ---------------------------------------------------------------------------
# Shared state fixture — backs every admin tool handler.
# ---------------------------------------------------------------------------
@pytest.fixture()
def state(tmp_path: Path) -> MagicMock:
    s = MagicMock()

    # plugin/skill loaders
    plugin_meta = make_plugin_meta(name="my-plugin", category="input")
    skill_meta = make_skill_meta(name="my-skill", category="process")
    s.plugin_loader = MagicMock()
    s.plugin_loader.load_all = AsyncMock(return_value={"my-plugin": plugin_meta})
    s.skill_loader = MagicMock()
    s.skill_loader.load_all = AsyncMock(return_value={"my-skill": skill_meta})

    # credentials + danger map
    s.credential_store = MagicMock()
    s.credential_store.list_services = MagicMock(return_value=[])
    s.danger_map = {}

    # runtime config
    s.runtime_config = MagicMock()
    s.runtime_config.disabled_entries = []
    s.runtime_config.snapshot = MagicMock(
        return_value={
            "llm_model": "claude-sonnet-4-6",
            "safe_mode": True,
            "disabled_entries": [],
        },
    )
    s.runtime_config.llm_api_key = "sk-redacted"
    s.runtime_config.embedding_api_key = ""
    s.runtime_config.update = MagicMock()
    s.runtime_config.rebuild_enabled = MagicMock()
    s.retriever = MagicMock()
    s.retriever.index_available = True

    # vault
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "garden").mkdir()
    (vault_root / "garden" / "x.md").write_text("# X\n")
    s.vault = MagicMock()
    s.vault.root = vault_root

    # agent loop
    s.agent_loop = MagicMock()
    s.agent_loop.get_entry = MagicMock(return_value=plugin_meta)
    s.agent_loop.run_entry_direct = AsyncMock(return_value={"status": "ok"})
    s.agent_loop._registry = {"my-plugin": plugin_meta, "my-skill": skill_meta}

    # canon
    s.canon_index = MagicMock()
    s.canon_index.list_active_concepts = AsyncMock(return_value=[])
    s.canon_index.list_proposals = AsyncMock(return_value=[])
    s.canon_index.list_actions = AsyncMock(return_value=[])
    s.canon_index.list_policies = AsyncMock(return_value=[])
    s.canon_service = MagicMock()
    s.canon_service.create_action_draft = AsyncMock(
        return_value="actions/2026-05-08T12-merge-foo.md",
    )
    s.canon_service.apply_action = AsyncMock(
        return_value=SimpleNamespace(
            action_path="actions/x.md",
            final_status="applied",
            affected_paths=["concepts/foo.md"],
            error=None,
        ),
    )
    s.canon_service.approve_action = AsyncMock(
        return_value=SimpleNamespace(
            action_path="actions/x.md",
            final_status="approved",
            affected_paths=[],
            error=None,
        ),
    )
    s.canon_service.reject_action = AsyncMock(return_value=None)
    s._canon_storage = MagicMock()
    s._canon_storage.read = AsyncMock(return_value="canon-note-content")

    # settings
    settings = MagicMock()
    settings.plugins_dir = tmp_path / "plugins"
    settings.plugins_dir.mkdir()
    s.settings = settings
    s.audit_outbox = None
    return s


@pytest.fixture()
def registry(state: MagicMock) -> ToolRegistry:
    reg = ToolRegistry()
    register_admin_tools(reg)
    return reg


@pytest.fixture()
def ctx(state: MagicMock) -> ToolContext:
    return ToolContext(user=_full_admin_user(), state=state, settings=state.settings)


# ---------------------------------------------------------------------------
# ListTools
# ---------------------------------------------------------------------------
class TestAdminCatalog:
    def test_admin_tool_names_published(self) -> None:
        # The exported constant must match what register_admin_tools wires
        # — sub-apps × actions, ``bsage run`` excluded.
        assert ADMIN_TOOL_NAMES == [
            "bsage_canon_apply",
            "bsage_canon_draft",
            "bsage_canon_list",
            "bsage_canon_status",
            "bsage_garden_list",
            "bsage_plugins_disable",
            "bsage_plugins_enable",
            "bsage_plugins_install",
            "bsage_plugins_list",
            "bsage_settings_get",
            "bsage_settings_set",
            "bsage_skills_list",
            "bsage_skills_run",
        ]

    def test_list_tools_renders_every_admin_tool(self, registry: ToolRegistry) -> None:
        names = {t.name for t in registry.list_tools()}
        for expected in ADMIN_TOOL_NAMES:
            assert expected in names

    def test_every_admin_tool_has_input_schema_object(self, registry: ToolRegistry) -> None:
        for tool in registry.list_tools():
            assert tool.inputSchema["type"] == "object"


# ---------------------------------------------------------------------------
# CallTool — one per sub-app.
# ---------------------------------------------------------------------------
class TestCallToolPerSubApp:
    @pytest.mark.asyncio
    async def test_skills_list(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        result = await registry.call_tool("bsage_skills_list", {}, ctx)
        assert "items" in result
        assert any(item["name"] == "my-skill" for item in result["items"])

    @pytest.mark.asyncio
    async def test_plugins_list(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        result = await registry.call_tool("bsage_plugins_list", {}, ctx)
        assert "items" in result
        assert any(item["name"] == "my-plugin" for item in result["items"])

    @pytest.mark.asyncio
    async def test_garden_list(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        result = await registry.call_tool("bsage_garden_list", {}, ctx)
        items = result["items"]
        assert any(entry["files"] == ["x.md"] for entry in items)

    @pytest.mark.asyncio
    async def test_canon_list_concepts(self, registry: ToolRegistry, ctx: ToolContext) -> None:
        result = await registry.call_tool("bsage_canon_list", {"kind": "concepts"}, ctx)
        assert result == {"kind": "concepts", "items": []}

    @pytest.mark.asyncio
    async def test_canon_draft(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        result = await registry.call_tool(
            "bsage_canon_draft",
            {"kind": "merge-concepts", "params": {"a": "b"}},
            ctx,
        )
        state.canon_service.create_action_draft.assert_awaited_once()
        assert result["status"] == "draft"
        assert result["path"].startswith("actions/")

    @pytest.mark.asyncio
    async def test_canon_apply_mode_apply(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        result = await registry.call_tool(
            "bsage_canon_apply",
            {"action_path": "actions/x.md", "mode": "apply"},
            ctx,
        )
        state.canon_service.apply_action.assert_awaited_once()
        assert result["final_status"] == "applied"

    @pytest.mark.asyncio
    async def test_canon_status_with_path(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        result = await registry.call_tool(
            "bsage_canon_status",
            {"path": "actions/x.md"},
            ctx,
        )
        state._canon_storage.read.assert_awaited_once_with("actions/x.md")
        assert result == {"path": "actions/x.md", "content": "canon-note-content"}

    @pytest.mark.asyncio
    async def test_settings_get_full_snapshot(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
    ) -> None:
        result = await registry.call_tool("bsage_settings_get", {}, ctx)
        snap = result["settings"]
        assert "llm_model" in snap
        assert snap["has_llm_api_key"] is True
        assert snap["has_embedding_api_key"] is False
        assert snap["index_available"] is True

    @pytest.mark.asyncio
    async def test_settings_set_dispatches_runtime_update(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        await registry.call_tool(
            "bsage_settings_set",
            {"key": "safe_mode", "value": False},
            ctx,
        )
        state.runtime_config.update.assert_called_once_with(safe_mode=False)

    @pytest.mark.asyncio
    async def test_skills_run(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        result = await registry.call_tool(
            "bsage_skills_run",
            {"name": "my-skill", "input": {"hello": "world"}},
            ctx,
        )
        state.agent_loop.run_entry_direct.assert_awaited_once_with("my-skill", {"hello": "world"})
        assert result == {"name": "my-skill", "result": {"status": "ok"}}

    @pytest.mark.asyncio
    async def test_plugins_enable_idempotent_noop(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        # plugin currently enabled (not in disabled_entries) → enable is no-op.
        result = await registry.call_tool("bsage_plugins_enable", {"name": "my-plugin"}, ctx)
        assert result == {"name": "my-plugin", "enabled": True, "changed": False}
        state.runtime_config.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_plugins_disable_changes_state(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        result = await registry.call_tool("bsage_plugins_disable", {"name": "my-plugin"}, ctx)
        assert result["changed"] is True
        assert result["enabled"] is False
        state.runtime_config.update.assert_called_once()


# ---------------------------------------------------------------------------
# Scope enforcement — admin tools require the same scope as the REST route.
# ---------------------------------------------------------------------------
class TestScopeEnforcement:
    @pytest.mark.asyncio
    async def test_settings_set_requires_config_write(
        self,
        registry: ToolRegistry,
        state: MagicMock,
    ) -> None:
        ctx = ToolContext(
            user=_FakeUser(scope=["bsage.config.read"]),  # missing config.write
            state=state,
            settings=state.settings,
        )
        with pytest.raises(ToolScopeDenied):
            await registry.call_tool(
                "bsage_settings_set",
                {"key": "safe_mode", "value": True},
                ctx,
            )

    @pytest.mark.asyncio
    async def test_canon_apply_requires_canon_apply_scope(
        self,
        registry: ToolRegistry,
        state: MagicMock,
    ) -> None:
        ctx = ToolContext(
            user=_FakeUser(scope=["bsage.canonicalization.read"]),
            state=state,
            settings=state.settings,
        )
        with pytest.raises(ToolScopeDenied):
            await registry.call_tool(
                "bsage_canon_apply",
                {"action_path": "actions/x.md", "mode": "apply"},
                ctx,
            )


# ---------------------------------------------------------------------------
# Validation — typo'd config key rejected before the runtime is touched.
# ---------------------------------------------------------------------------
class TestInputValidation:
    @pytest.mark.asyncio
    async def test_settings_set_unknown_key_rejected(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        state: MagicMock,
    ) -> None:
        with pytest.raises(ToolError):
            await registry.call_tool(
                "bsage_settings_set",
                {"key": "not_a_real_key", "value": 1},
                ctx,
            )
        state.runtime_config.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_canon_apply_invalid_mode_rejected(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
    ) -> None:
        with pytest.raises(ToolError):
            await registry.call_tool(
                "bsage_canon_apply",
                {"action_path": "actions/x.md", "mode": "delete"},
                ctx,
            )
