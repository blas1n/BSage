"""Tests for the MCP OAuth protected-resource wrapper (RFC 9728)."""

from __future__ import annotations

from bsage.mcp.oauth_protected_resource import (
    build_protected_resource_metadata,
    wrap_mcp_with_oauth_401,
)


def test_protected_resource_metadata_shape():
    body = build_protected_resource_metadata(
        resource_url="https://bsage.bsvibe.dev",
        authorization_server="https://auth.bsvibe.dev",
        scopes_supported=["bsage:*"],
    )
    assert body["resource"] == "https://bsage.bsvibe.dev"
    assert body["authorization_servers"] == ["https://auth.bsvibe.dev"]
    assert body["bearer_methods_supported"] == ["header"]
    assert "bsage:*" in body["scopes_supported"]


async def test_wrapper_passes_through_when_bearer_present():
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append("called")

    wrapped = wrap_mcp_with_oauth_401(inner)
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"authorization", b"Bearer abc.def.ghi")],
        "scheme": "https",
        "server": ("test", 443),
    }
    await wrapped(scope, None, None)
    assert seen == ["called"]


async def test_wrapper_returns_401_with_www_authenticate_when_missing():
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    async def inner(scope, receive, _send):
        sent.append({"type": "inner-called"})

    wrapped = wrap_mcp_with_oauth_401(inner)
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"x-forwarded-proto", b"https"),
            (b"x-forwarded-host", b"bsage.bsvibe.dev"),
        ],
        "scheme": "http",
        "server": ("internal", 80),
    }
    await wrapped(scope, None, send)
    assert not any(m.get("type") == "inner-called" for m in sent)
    start = next(m for m in sent if m.get("type") == "http.response.start")
    assert start["status"] == 401
    www = next(v for k, v in start["headers"] if k == b"www-authenticate")
    assert b"resource_metadata=" in www
    assert b"bsage.bsvibe.dev/.well-known/oauth-protected-resource" in www


async def test_wrapper_options_preflight_passes_through():
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append("called")

    wrapped = wrap_mcp_with_oauth_401(inner)
    scope = {
        "type": "http",
        "method": "OPTIONS",
        "headers": [],
        "scheme": "https",
        "server": ("test", 443),
    }
    await wrapped(scope, None, None)
    assert seen == ["called"]
