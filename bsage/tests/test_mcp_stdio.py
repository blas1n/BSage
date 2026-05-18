"""Tests for the stdio MCP transport (``bsage.mcp.stdio``).

The stdio transport carries no per-request HTTP headers, so a
permissioned MCP tool would see ``ctx.user is None`` and deny every
call. When ``BSAGE_MCP_PAT`` is set, ``run_stdio_server`` resolves that
PAT once at startup — through the same ``bsvibe_authz`` dispatch the
Streamable HTTP transport uses — and pins the principal on
``state.mcp_principal`` so the dispatcher's ``_resolve_principal``
returns it for every stdio call.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.mcp import stdio


class _FakeStdioCtx:
    """Async context manager standing in for ``mcp.server.stdio.stdio_server``."""

    async def __aenter__(self) -> tuple[MagicMock, MagicMock]:
        return (MagicMock(), MagicMock())

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class TestResolveStdioPrincipal:
    @pytest.mark.asyncio
    async def test_returns_none_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(stdio.STDIO_TOKEN_ENV, raising=False)
        assert await stdio._resolve_stdio_principal(MagicMock()) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_env_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(stdio.STDIO_TOKEN_ENV, "   ")
        assert await stdio._resolve_stdio_principal(MagicMock()) is None

    @pytest.mark.asyncio
    async def test_resolves_pat_via_bsvibe_authz_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A PAT in ``$BSAGE_MCP_PAT`` is resolved through the shared
        header resolver with a ``Bearer`` Authorization header."""
        monkeypatch.setenv(stdio.STDIO_TOKEN_ENV, "pat-xyz")
        seen: dict[str, Any] = {}

        async def _fake_resolve(headers: Any, state: Any) -> str:
            seen["headers"] = dict(headers)
            seen["state"] = state
            return "principal-obj"

        monkeypatch.setattr(
            "bsage.mcp.streamable_http.resolve_principal_from_headers",
            _fake_resolve,
        )
        state = MagicMock()
        result = await stdio._resolve_stdio_principal(state)

        assert result == "principal-obj"
        assert seen["headers"]["authorization"] == "Bearer pat-xyz"
        assert seen["state"] is state


class TestRunStdioServerPinsPrincipal:
    @pytest.mark.asyncio
    async def test_pins_resolved_principal_on_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``run_stdio_server`` threads the resolved principal onto
        ``state.mcp_principal`` — the dispatcher's ``_resolve_principal``
        reads it back, so ``ctx.user`` is the real principal on stdio.
        """
        app_state = MagicMock()
        app_state.initialize = AsyncMock()
        app_state.shutdown = AsyncMock()

        fake_server = MagicMock()
        fake_server.create_initialization_options = MagicMock(return_value={})
        fake_server.run = AsyncMock()

        monkeypatch.setattr(stdio, "_configure_stdio_logging", lambda: None)
        monkeypatch.setattr(stdio, "_resolve_stdio_principal", AsyncMock(return_value="PRIN"))
        monkeypatch.setattr("bsage.core.config.get_settings", lambda: MagicMock())
        monkeypatch.setattr("bsage.gateway.dependencies.AppState", lambda _s: app_state)
        monkeypatch.setattr("bsage.mcp.server.build_server", lambda _s: fake_server)
        monkeypatch.setattr("mcp.server.stdio.stdio_server", lambda: _FakeStdioCtx())

        await stdio.run_stdio_server()

        assert app_state.mcp_principal == "PRIN"
        app_state.initialize.assert_awaited_once()
        app_state.shutdown.assert_awaited_once()
        fake_server.run.assert_awaited_once()
