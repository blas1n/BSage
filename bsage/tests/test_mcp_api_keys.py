"""Tests for bsage.mcp.api_keys — long-lived API key (PAT) store for MCP."""

from __future__ import annotations

from pathlib import Path

import pytest

from bsage.mcp.api_keys import MCPAPIKeyStore, hash_token


@pytest.fixture()
def store(tmp_path: Path) -> MCPAPIKeyStore:
    return MCPAPIKeyStore(tmp_path / "api_keys.json")


class TestKeyIssuance:
    @pytest.mark.asyncio
    async def test_create_returns_raw_token_and_record(self, store: MCPAPIKeyStore) -> None:
        result = await store.create(name="cursor-laptop", tenant_id="t1")
        assert result.token.startswith("bsg_mcp_")
        assert len(result.token) >= 40
        assert result.record.id
        assert result.record.name == "cursor-laptop"
        assert result.record.tenant_id == "t1"
        assert result.record.revoked_at is None
        assert result.record.last_used_at is None

    @pytest.mark.asyncio
    async def test_token_is_hashed_at_rest(self, store: MCPAPIKeyStore, tmp_path: Path) -> None:
        result = await store.create(name="x", tenant_id="t1")
        # Raw token must not appear anywhere in the on-disk JSON
        contents = (tmp_path / "api_keys.json").read_text()
        assert result.token not in contents
        assert hash_token(result.token) in contents

    @pytest.mark.asyncio
    async def test_create_assigns_unique_ids(self, store: MCPAPIKeyStore) -> None:
        a = await store.create(name="a", tenant_id="t1")
        b = await store.create(name="b", tenant_id="t1")
        assert a.record.id != b.record.id


class TestList:
    @pytest.mark.asyncio
    async def test_list_filters_by_tenant(self, store: MCPAPIKeyStore) -> None:
        a = await store.create(name="t1-key", tenant_id="t1")
        b = await store.create(name="t2-key", tenant_id="t2")
        t1_keys = await store.list_for_tenant("t1")
        assert [k.id for k in t1_keys] == [a.record.id]
        t2_keys = await store.list_for_tenant("t2")
        assert [k.id for k in t2_keys] == [b.record.id]

    @pytest.mark.asyncio
    async def test_list_excludes_revoked_by_default(self, store: MCPAPIKeyStore) -> None:
        active = await store.create(name="active", tenant_id="t1")
        revoked = await store.create(name="revoked", tenant_id="t1")
        await store.revoke(revoked.record.id, tenant_id="t1")
        ids = [k.id for k in await store.list_for_tenant("t1")]
        assert active.record.id in ids
        assert revoked.record.id not in ids
        # include_revoked=True returns both
        all_ids = [k.id for k in await store.list_for_tenant("t1", include_revoked=True)]
        assert revoked.record.id in all_ids


class TestRevoke:
    @pytest.mark.asyncio
    async def test_revoke_marks_record(self, store: MCPAPIKeyStore) -> None:
        r = await store.create(name="x", tenant_id="t1")
        await store.revoke(r.record.id, tenant_id="t1")
        all_keys = await store.list_for_tenant("t1", include_revoked=True)
        assert all_keys[0].revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_rejects_cross_tenant(self, store: MCPAPIKeyStore) -> None:
        r = await store.create(name="x", tenant_id="t1")
        with pytest.raises(KeyError):
            await store.revoke(r.record.id, tenant_id="t2")

    @pytest.mark.asyncio
    async def test_revoke_unknown_id_raises(self, store: MCPAPIKeyStore) -> None:
        with pytest.raises(KeyError):
            await store.revoke("missing", tenant_id="t1")


class TestVerify:
    @pytest.mark.asyncio
    async def test_verify_returns_record_for_valid_token(self, store: MCPAPIKeyStore) -> None:
        r = await store.create(name="x", tenant_id="t1")
        record = await store.verify(r.token)
        assert record is not None
        assert record.id == r.record.id

    @pytest.mark.asyncio
    async def test_verify_returns_none_for_unknown_token(self, store: MCPAPIKeyStore) -> None:
        assert await store.verify("bsg_mcp_unknown") is None
        assert await store.verify("not-a-bsg-token") is None
        assert await store.verify("") is None

    @pytest.mark.asyncio
    async def test_verify_returns_none_for_revoked_token(self, store: MCPAPIKeyStore) -> None:
        r = await store.create(name="x", tenant_id="t1")
        await store.revoke(r.record.id, tenant_id="t1")
        assert await store.verify(r.token) is None

    @pytest.mark.asyncio
    async def test_verify_updates_last_used_at(self, store: MCPAPIKeyStore) -> None:
        r = await store.create(name="x", tenant_id="t1")
        assert r.record.last_used_at is None
        await store.verify(r.token)
        ks = await store.list_for_tenant("t1")
        assert ks[0].last_used_at is not None


class TestPersistence:
    @pytest.mark.asyncio
    async def test_round_trip_via_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "api_keys.json"
        s1 = MCPAPIKeyStore(path)
        r = await s1.create(name="persist", tenant_id="t1")

        s2 = MCPAPIKeyStore(path)
        record = await s2.verify(r.token)
        assert record is not None
        assert record.name == "persist"


def test_hash_token_is_deterministic() -> None:
    assert hash_token("bsg_mcp_abc") == hash_token("bsg_mcp_abc")
    assert hash_token("a") != hash_token("b")
    # sha256 hex = 64 chars
    assert len(hash_token("x")) == 64
