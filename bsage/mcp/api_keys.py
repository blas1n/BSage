"""Long-lived MCP API keys (PAT pattern).

Storage: a single JSON file under the configured data dir. We store
SHA-256 hashes only — the raw token is shown to the user once at
creation time. Tokens carry a ``bsg_mcp_`` prefix so they're easy to
spot in logs and pickups by GitHub secret scanning.

This is intentionally separate from the ``CredentialStore`` (which
handles plugin credentials with reversible Fernet encryption) — for
auth tokens we want one-way hashes so a leaked file can't be replayed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

TOKEN_PREFIX = "bsg_mcp_"
_TOKEN_RANDOM_BYTES = 32  # → 43-char base64url


def hash_token(token: str) -> str:
    """SHA-256 hex digest of the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class MCPAPIKeyRecord:
    """On-disk record for an issued MCP API key."""

    id: str
    name: str
    tenant_id: str
    hashed_token: str
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None
    user_id: str | None = None  # who issued it; optional for stdio paths


@dataclass
class MCPAPIKeyIssuance:
    """Result of ``MCPAPIKeyStore.create`` — raw token shown ONCE."""

    token: str
    record: MCPAPIKeyRecord


class MCPAPIKeyStore:
    """JSON-backed store for MCP API keys.

    All operations are async + serialised behind an asyncio.Lock so a
    concurrent create/revoke pair from the gateway can't corrupt the file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._cache: dict[str, MCPAPIKeyRecord] | None = None

    async def create(
        self,
        *,
        name: str,
        tenant_id: str,
        user_id: str | None = None,
    ) -> MCPAPIKeyIssuance:
        async with self._lock:
            records = await self._load_locked()
            token = TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_RANDOM_BYTES)
            key_id = secrets.token_urlsafe(12)
            record = MCPAPIKeyRecord(
                id=key_id,
                name=name,
                tenant_id=tenant_id,
                hashed_token=hash_token(token),
                created_at=_now(),
                user_id=user_id,
            )
            records[key_id] = record
            await self._save_locked(records)
            logger.info("mcp_api_key_issued", id=key_id, tenant=tenant_id, name=name)
            return MCPAPIKeyIssuance(token=token, record=record)

    async def list_for_tenant(
        self, tenant_id: str, *, include_revoked: bool = False
    ) -> list[MCPAPIKeyRecord]:
        async with self._lock:
            records = await self._load_locked()
        out = [
            r
            for r in records.values()
            if r.tenant_id == tenant_id and (include_revoked or r.revoked_at is None)
        ]
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out

    async def revoke(self, key_id: str, *, tenant_id: str) -> None:
        async with self._lock:
            records = await self._load_locked()
            if key_id not in records or records[key_id].tenant_id != tenant_id:
                raise KeyError(key_id)
            records[key_id].revoked_at = _now()
            await self._save_locked(records)
            logger.info("mcp_api_key_revoked", id=key_id, tenant=tenant_id)

    async def verify(self, token: str) -> MCPAPIKeyRecord | None:
        """Return the record matching this token, or None.

        Bumps ``last_used_at`` on success.
        """
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        digest = hash_token(token)
        async with self._lock:
            records = await self._load_locked()
            for r in records.values():
                if r.hashed_token == digest:
                    if r.revoked_at is not None:
                        return None
                    r.last_used_at = _now()
                    await self._save_locked(records)
                    return r
        return None

    # -- internal -----------------------------------------------------------

    async def _load_locked(self) -> dict[str, MCPAPIKeyRecord]:
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            self._cache = {}
            return self._cache
        try:
            raw = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        except OSError:
            self._cache = {}
            return self._cache
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            logger.warning("mcp_api_keys_file_corrupt", path=str(self._path))
            self._cache = {}
            return self._cache
        self._cache = {k: MCPAPIKeyRecord(**v) for k, v in data.items() if isinstance(v, dict)}
        return self._cache

    async def _save_locked(self, records: dict[str, MCPAPIKeyRecord]) -> None:
        self._cache = records
        payload = json.dumps({k: asdict(v) for k, v in records.items()}, indent=2, sort_keys=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._path.write_text, payload, encoding="utf-8")
