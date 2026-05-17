"""Tests for the Streamable HTTP MCP transport (``bsage.mcp.streamable_http``).

Covers:

* ``build_streamable_http_app`` returns a ``StreamableHTTPSessionManager``
  + an ASGI app.
* ``resolve_principal_from_headers`` — no header → ``None``; a valid
  header → the resolved principal (auth mocked at the bsvibe-authz
  boundary); an auth failure → ``None`` (never raises / 500s).
* **Regression guard for the SSE-era bug**: a permissioned tool invoked
  with the principal context-var set gets a *non-None* ``ctx.user`` in
  the dispatcher. The SSE transport authenticated only the connection
  and left ``ctx.user = None``, so every permissioned MCP tool denied
  over HTTP. Streamable HTTP threads the per-request principal — this
  test fails if that threading regresses.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from bsage.mcp import server as mcp_server
from bsage.mcp import streamable_http
from bsage.mcp.streamable_http import (
    build_streamable_http_app,
    get_request_principal,
    resolve_principal_from_headers,
)


@pytest.fixture()
def state(tmp_path: Path) -> MagicMock:
    s = MagicMock()
    s.vault = MagicMock()
    s.vault.root = tmp_path
    s.vault.resolve_path = MagicMock(side_effect=lambda p: tmp_path / p)
    s.embedder = MagicMock()
    s.embedder.enabled = False
    s.vector_store = None
    s.retriever = MagicMock()
    s.retriever.search = AsyncMock(return_value="result")
    s.index_reader = MagicMock()
    s.index_reader.get_all_summaries = AsyncMock(return_value=[])
    s.garden_writer = MagicMock()
    s.runtime_config = MagicMock()
    s.runtime_config.disabled_entries = []
    s.plugin_loader = MagicMock()
    s.plugin_loader.load_all = AsyncMock(return_value={})
    s.skill_loader = MagicMock()
    s.skill_loader.load_all = AsyncMock(return_value={})
    s.credential_store = MagicMock()
    s.credential_store.list_services = MagicMock(return_value=[])
    s.danger_map = {}
    s.audit_outbox = None
    s.settings = MagicMock()
    s.settings.mcp_canon_mutation_enabled = False
    # No connection-time mcp_principal — the transport resolves per-request.
    del s.mcp_principal
    return s


class TestBuildStreamableHttpApp:
    def test_returns_manager_and_asgi_app(self, state: MagicMock) -> None:
        manager, asgi_app = build_streamable_http_app(state)
        assert isinstance(manager, StreamableHTTPSessionManager)
        assert callable(asgi_app)

    @pytest.mark.asyncio
    async def test_asgi_shim_sets_principal_contextvar_during_request(
        self, state: MagicMock
    ) -> None:
        # The HTTP ASGI shim must resolve the principal from the request
        # headers and have it visible (via the context-var) while
        # manager.handle_request runs — that is what threads ctx.user.
        manager, asgi_app = build_streamable_http_app(state)

        fake_user = MagicMock(id="shim-user", is_service=False)
        seen: dict[str, object] = {}

        async def _fake_handle_request(scope, receive, send) -> None:
            seen["principal"] = get_request_principal()

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [(b"authorization", b"Bearer good.jwt.token")],
        }
        with (
            patch.object(manager, "handle_request", new=_fake_handle_request),
            patch(
                "bsvibe_authz.deps.get_current_user",
                new=AsyncMock(return_value=fake_user),
            ),
        ):
            await asgi_app(scope, None, None)

        assert seen["principal"] is fake_user
        # After the request the context-var is reset back to the default.
        assert get_request_principal() is None

    @pytest.mark.asyncio
    async def test_asgi_shim_forwards_non_http_scopes(self, state: MagicMock) -> None:
        manager, asgi_app = build_streamable_http_app(state)
        forwarded: list[str] = []

        async def _fake_handle_request(scope, receive, send) -> None:
            forwarded.append(scope["type"])

        with patch.object(manager, "handle_request", new=_fake_handle_request):
            await asgi_app({"type": "lifespan"}, None, None)

        assert forwarded == ["lifespan"]


class TestResolvePrincipalFromHeaders:
    @pytest.mark.asyncio
    async def test_no_authorization_header_returns_none(self, state: MagicMock) -> None:
        principal = await resolve_principal_from_headers({}, state)
        assert principal is None

    @pytest.mark.asyncio
    async def test_valid_header_returns_resolved_principal(self, state: MagicMock) -> None:
        fake_user = MagicMock(id="user-123", is_service=False)
        with patch(
            "bsvibe_authz.deps.get_current_user",
            new=AsyncMock(return_value=fake_user),
        ):
            principal = await resolve_principal_from_headers(
                {"authorization": "Bearer valid.jwt.token"}, state
            )
        assert principal is fake_user
        assert principal.id == "user-123"

    @pytest.mark.asyncio
    async def test_auth_failure_returns_none_never_raises(self, state: MagicMock) -> None:
        # A bad token must degrade to anonymous (None) — never a 500.
        with patch(
            "bsvibe_authz.deps.get_current_user",
            new=AsyncMock(side_effect=Exception("invalid token")),
        ):
            principal = await resolve_principal_from_headers(
                {"authorization": "Bearer garbage"}, state
            )
        assert principal is None


class TestPrincipalThreadsIntoToolContext:
    """Regression guard — the SSE-era ``ctx.user = None`` bug is fixed.

    The Streamable HTTP ASGI shim resolves the principal and stashes it
    on the ``_mcp_principal_var`` context-var; the dispatcher
    (``_dispatch_via_registry``) reads it back via ``_resolve_principal``.
    With the var set, a permissioned tool's ``ToolContext.user`` MUST be
    the real principal — not ``None``.
    """

    @pytest.mark.asyncio
    async def test_dispatcher_threads_context_var_principal(self, state: MagicMock) -> None:
        from pydantic import BaseModel

        from bsage.mcp.api import Tool, ToolContext, ToolRegistry

        class _Empty(BaseModel):
            pass

        class _Out(BaseModel):
            ok: bool = True

        captured: dict[str, object] = {}

        async def _handler(_args: BaseModel, ctx: ToolContext) -> dict[str, bool]:
            captured["user"] = ctx.user
            return {"ok": True}

        registry = ToolRegistry()
        registry.register(
            Tool(
                name="permissioned_probe",
                description="probe that records ctx.user",
                input_schema=_Empty,
                output_schema=_Out,
                handler=_handler,
                # required_permission left None so the dispatcher does not
                # need a live OpenFGA model — the assertion is purely that
                # the *principal threads*, which is the bug under test.
            )
        )

        fake_user = MagicMock(id="principal-xyz", is_service=False)
        token = streamable_http._mcp_principal_var.set(fake_user)
        try:
            assert get_request_principal() is fake_user
            await mcp_server._dispatch_via_registry(state, registry, "permissioned_probe", {})
        finally:
            streamable_http._mcp_principal_var.reset(token)

        assert captured["user"] is fake_user, (
            "ctx.user must be the per-request principal, not None — "
            "this is the SSE-era bug the Streamable HTTP migration fixes"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_user_is_none_without_request_context(self, state: MagicMock) -> None:
        # Outside an HTTP request (stdio transport, no context-var set),
        # ctx.user falls back to None — domain read tools still work.
        from pydantic import BaseModel

        from bsage.mcp.api import Tool, ToolContext, ToolRegistry

        class _Empty(BaseModel):
            pass

        class _Out(BaseModel):
            ok: bool = True

        captured: dict[str, object] = {}

        async def _handler(_args: BaseModel, ctx: ToolContext) -> dict[str, bool]:
            captured["user"] = ctx.user
            return {"ok": True}

        registry = ToolRegistry()
        registry.register(
            Tool(
                name="probe",
                description="probe",
                input_schema=_Empty,
                output_schema=_Out,
                handler=_handler,
            )
        )
        await mcp_server._dispatch_via_registry(state, registry, "probe", {})
        assert captured["user"] is None
