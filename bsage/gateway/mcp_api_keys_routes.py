"""REST routes for MCP API key (PAT) management.

Issued under the active tenant. Raw token is returned ONCE at creation;
subsequent listings return only metadata. Tenant isolation enforced —
keys are never visible across tenants.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field


class _CreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="Human label for this key")


class _CreateResponse(BaseModel):
    id: str
    name: str
    token: str  # raw — shown once
    created_at: str


class _KeyResponse(BaseModel):
    id: str
    name: str
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None


def create_mcp_api_keys_routes(state: Any) -> APIRouter:
    router = APIRouter(
        prefix="/api/mcp/api-keys",
        tags=["mcp-api-keys"],
        dependencies=[Depends(state.get_current_user)],
    )

    _principal = state.get_current_user

    @router.post("", response_model=_CreateResponse, status_code=status.HTTP_201_CREATED)
    async def create_key(
        body: _CreateRequest,
        principal: Any = Depends(_principal),
    ) -> _CreateResponse:
        tenant_id = getattr(principal, "active_tenant_id", None) or "default"
        user_id = getattr(principal, "id", None)
        issued = await state.mcp_api_keys.create(
            name=body.name,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return _CreateResponse(
            id=issued.record.id,
            name=issued.record.name,
            token=issued.token,
            created_at=issued.record.created_at,
        )

    @router.get("", response_model=list[_KeyResponse])
    async def list_keys(
        principal: Any = Depends(_principal),
    ) -> list[_KeyResponse]:
        tenant_id = getattr(principal, "active_tenant_id", None) or "default"
        records = await state.mcp_api_keys.list_for_tenant(tenant_id)
        return [
            _KeyResponse(
                id=r.id,
                name=r.name,
                created_at=r.created_at,
                last_used_at=r.last_used_at,
                revoked_at=r.revoked_at,
            )
            for r in records
        ]

    @router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_key(
        key_id: str,
        principal: Any = Depends(_principal),
    ) -> None:
        tenant_id = getattr(principal, "active_tenant_id", None) or "default"
        try:
            await state.mcp_api_keys.revoke(key_id, tenant_id=tenant_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="API key not found") from None

    # `asdict` import keeps a reference so the linter doesn't strip it; used
    # implicitly by tests that introspect record shape.
    _ = asdict

    return router
