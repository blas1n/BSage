"""SSE auth path test — verify PAT tokens (bsg_mcp_*) authenticate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bsage.mcp.api_keys import MCPAPIKeyStore
from bsage.mcp.sse import _MCPKeyPrincipal


@pytest.fixture()
def store(tmp_path: Path) -> MCPAPIKeyStore:
    return MCPAPIKeyStore(tmp_path / "mcp_api_keys.json")


def _make_request(authorization: str | None = None) -> MagicMock:
    req = MagicMock()
    headers = {}
    if authorization is not None:
        headers["authorization"] = authorization
    req.headers = headers
    req.scope = {"headers": []}
    return req


class TestPATAuthPath:
    """The async closure inside create_sse_routes builds a server which
    requires a real AppState. To unit-test the PAT path in isolation, we
    re-implement the auth logic via the same TOKEN_PREFIX check.
    """

    @pytest.mark.asyncio
    async def test_valid_pat_returns_synthetic_principal(self, store: MCPAPIKeyStore) -> None:
        issued = await store.create(name="x", tenant_id="t1", user_id="user-1")
        record = await store.verify(issued.token)
        assert record is not None
        principal = _MCPKeyPrincipal(
            id=record.user_id or f"mcp-key:{record.id}",
            active_tenant_id=record.tenant_id,
        )
        assert principal.id == "user-1"
        assert principal.active_tenant_id == "t1"
        assert principal.auth_method == "mcp_api_key"

    @pytest.mark.asyncio
    async def test_revoked_pat_rejected(self, store: MCPAPIKeyStore) -> None:
        issued = await store.create(name="x", tenant_id="t1")
        await store.revoke(issued.record.id, tenant_id="t1")
        assert await store.verify(issued.token) is None


class TestPATBranchIsolation:
    """Verify the auth helper logic without spinning up SSE (which hangs).

    The synchronous TestClient cannot timeout SSE streams cleanly, so we
    test the PAT path by exercising the underlying ``MCPAPIKeyStore.verify``
    directly. That's the actual security boundary; the route just plumbs
    the result.
    """

    @pytest.mark.asyncio
    async def test_unknown_pat_prefix_token_returns_none(self, store: MCPAPIKeyStore) -> None:
        # Looks like a PAT but isn't issued
        assert await store.verify("bsg_mcp_someoneelse") is None

    @pytest.mark.asyncio
    async def test_non_pat_token_returns_none(self, store: MCPAPIKeyStore) -> None:
        # JWT-shaped token must NOT match the PAT path
        assert await store.verify("eyJhbGciOiJIUzI1NiJ9.foo.bar") is None
