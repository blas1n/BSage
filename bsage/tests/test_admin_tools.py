"""Tests for the first-class admin MCP tools (Phase 7 / TASK-004).

Each ``bsage <subapp>`` Typer sub-app gets a matching ``bsage_<subapp>_<action>``
first-class :class:`bsage.mcp.api.Tool`. Tests cover:

* the full admin catalog is registered (ListTools includes every name);
* one CallTool round-trip per sub-app, with a duck-typed principal,
  confirms the handler reaches the same service-layer call the REST
  route uses.

Tier 5 Phase 3a — admin tools enforce a ``required_permission`` dot
string via ``bsvibe_authz.check_tenant_permission`` (OpenFGA), not the
legacy JWT ``scope`` claim. ``check_tenant_permission`` is permissive
when OpenFGA is unconfigured (``openfga_api_url`` empty), so positive
round-trips pass against a permissive authz settings; the deny-path
tests inject a settings carrying ``openfga_api_url`` plus a fake fga
client returning ``False``.

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
    def __init__(
        self,
        *,
        id: str = "admin",  # noqa: A002
        active_tenant_id: str | None = "tenant-a",
    ) -> None:
        self.id = id
        self.email = None
        self.is_service = False
        self.is_demo = False
        self.active_tenant_id = active_tenant_id
        self.app_metadata: dict[str, object] = {}


class _FakeFga:
    """OpenFGA client stub — returns a fixed allow/deny verdict."""

    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed

    async def check(self, user: str, relation: str, object_: str) -> bool:
        return self._allowed

    async def write_tuple(self, user: str, relation: str, object_: str) -> None:
        return None


def _permissive_settings() -> SimpleNamespace:
    """bsvibe_authz.Settings-shaped object with OpenFGA *unconfigured*
    (``openfga_api_url`` empty) — ``check_tenant_permission`` is then
    permissive, mirroring the test/dev/current-prod posture."""
    return SimpleNamespace(openfga_api_url="", permission_cache_ttl_s=30)


def _enforcing_settings() -> SimpleNamespace:
    """bsvibe_authz.Settings-shaped object with OpenFGA *configured* —
    flips ``check_tenant_permission`` out of permissive mode so the
    deny path is exercised."""
    return SimpleNamespace(
        openfga_api_url="http://openfga.test",
        permission_cache_ttl_s=30,
    )


def _full_admin_user() -> _FakeUser:
    """A principal with an active tenant — passes every admin tool when
    OpenFGA is unconfigured (permissive mode)."""
    return _FakeUser()


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
    # Permissive authz settings (OpenFGA unconfigured) → every
    # ``required_permission`` admin tool is allowed for an authenticated
    # principal, exercising the handler/service path. The deny-path
    # tests below build their own enforcing context.
    from bsvibe_authz import PermissionCache

    return ToolContext(
        user=_full_admin_user(),
        state=state,
        settings=_permissive_settings(),
        fga=_FakeFga(allowed=True),
        cache=PermissionCache(ttl_s=30),
    )


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
# Permission enforcement — Tier 5: admin tools run the same OpenFGA
# ``check_tenant_permission`` the REST routes' ``require_permission`` does.
# ---------------------------------------------------------------------------
class TestPermissionEnforcement:
    def _denying_ctx(self, state: MagicMock) -> ToolContext:
        """Context whose OpenFGA check always denies — settings carry an
        ``openfga_api_url`` (out of permissive mode) and the fake fga
        returns ``False`` for every ``check``."""
        from bsvibe_authz import PermissionCache

        return ToolContext(
            user=_FakeUser(),
            state=state,
            settings=_enforcing_settings(),
            fga=_FakeFga(allowed=False),
            cache=PermissionCache(ttl_s=30),
        )

    @pytest.mark.asyncio
    async def test_settings_set_denied_when_openfga_denies(
        self,
        registry: ToolRegistry,
        state: MagicMock,
    ) -> None:
        ctx = self._denying_ctx(state)
        with pytest.raises(ToolScopeDenied):
            await registry.call_tool(
                "bsage_settings_set",
                {"key": "safe_mode", "value": True},
                ctx,
            )

    @pytest.mark.asyncio
    async def test_canon_apply_denied_when_openfga_denies(
        self,
        registry: ToolRegistry,
        state: MagicMock,
    ) -> None:
        ctx = self._denying_ctx(state)
        with pytest.raises(ToolScopeDenied):
            await registry.call_tool(
                "bsage_canon_apply",
                {"action_path": "actions/x.md", "mode": "apply"},
                ctx,
            )

    @pytest.mark.asyncio
    async def test_anonymous_principal_denied_on_permissioned_tool(
        self,
        registry: ToolRegistry,
        state: MagicMock,
    ) -> None:
        # No principal at all → permissioned tool denies before the
        # OpenFGA call (cannot resolve a user).
        ctx = ToolContext(
            user=None,
            state=state,
            settings=_permissive_settings(),
        )
        with pytest.raises(ToolScopeDenied):
            await registry.call_tool(
                "bsage_canon_apply",
                {"action_path": "actions/x.md", "mode": "apply"},
                ctx,
            )

    @pytest.mark.asyncio
    async def test_no_active_tenant_denied_when_openfga_configured(
        self,
        registry: ToolRegistry,
        state: MagicMock,
    ) -> None:
        # A principal with no active tenant cannot resolve a
        # ``tenant:<id>`` object — ``check_tenant_permission`` returns
        # False once OpenFGA is configured.
        from bsvibe_authz import PermissionCache

        ctx = ToolContext(
            user=_FakeUser(active_tenant_id=None),
            state=state,
            settings=_enforcing_settings(),
            fga=_FakeFga(allowed=True),
            cache=PermissionCache(ttl_s=30),
        )
        with pytest.raises(ToolScopeDenied):
            await registry.call_tool(
                "bsage_settings_set",
                {"key": "safe_mode", "value": True},
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
