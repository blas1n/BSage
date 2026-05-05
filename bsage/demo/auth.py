"""BSage demo auth — verifies the demo JWT.

Like BSupervisor, BSage demo uses a shared tenant (its data model is
single-vault per process). The JWT verifies the visitor has a valid
session, but read-only browse is the only mode.
"""

from __future__ import annotations

import os
import uuid

from bsvibe_demo import DemoJWTError, decode_demo_jwt
from fastapi import HTTPException, Request, status

DEMO_COOKIE_NAME = "bsvibe_demo_session"
DEMO_SHARED_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000a4900")


def get_demo_jwt_secret() -> str:
    secret = os.environ.get("DEMO_JWT_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DEMO_JWT_SECRET not configured on demo backend",
        )
    return secret


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(DEMO_COOKIE_NAME)


async def require_demo_session(request: Request) -> uuid.UUID:
    secret = get_demo_jwt_secret()
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Demo session not started — POST /api/v1/demo/session first",
        )
    try:
        claims = decode_demo_jwt(token, secret=secret)
    except DemoJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid demo session: {e}",
        ) from e
    return claims.tenant_id
