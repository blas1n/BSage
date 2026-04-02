"""Tests for bsage.gateway.rate_limit — sliding window rate limiter."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.gateway.rate_limit import RateLimiter, RateLimitMiddleware, _get_client_ip


class TestRateLimiter:
    """Unit tests for the RateLimiter class."""

    def test_allows_requests_under_limit(self) -> None:
        limiter = RateLimiter(requests_per_minute=5)
        for _ in range(5):
            allowed, remaining = limiter.is_allowed("1.2.3.4")
            assert allowed is True
        assert remaining == 0

    def test_rejects_requests_over_limit(self) -> None:
        limiter = RateLimiter(requests_per_minute=3)
        for _ in range(3):
            limiter.is_allowed("1.2.3.4")
        allowed, remaining = limiter.is_allowed("1.2.3.4")
        assert allowed is False
        assert remaining == 0

    def test_different_ips_tracked_separately(self) -> None:
        limiter = RateLimiter(requests_per_minute=2)
        limiter.is_allowed("1.1.1.1")
        limiter.is_allowed("1.1.1.1")
        # IP 1.1.1.1 is at limit
        allowed, _ = limiter.is_allowed("1.1.1.1")
        assert allowed is False
        # IP 2.2.2.2 is fresh
        allowed, remaining = limiter.is_allowed("2.2.2.2")
        assert allowed is True
        assert remaining == 1

    def test_expired_timestamps_are_pruned(self) -> None:
        limiter = RateLimiter(requests_per_minute=2)
        # Manually inject old timestamps
        state = limiter._clients["1.2.3.4"]
        state.timestamps = [time.monotonic() - 120, time.monotonic() - 90]
        # Old timestamps should be pruned, so new request is allowed
        allowed, remaining = limiter.is_allowed("1.2.3.4")
        assert allowed is True
        assert remaining == 1

    def test_limit_property(self) -> None:
        limiter = RateLimiter(requests_per_minute=42)
        assert limiter.limit == 42

    def test_remaining_decreases(self) -> None:
        limiter = RateLimiter(requests_per_minute=5)
        _, r1 = limiter.is_allowed("1.2.3.4")
        _, r2 = limiter.is_allowed("1.2.3.4")
        assert r1 == 4
        assert r2 == 3

    def test_stale_clients_are_evicted(self) -> None:
        limiter = RateLimiter(requests_per_minute=5)
        # Inject a stale client with old timestamps
        state = limiter._clients["stale-ip"]
        state.timestamps = [time.monotonic() - 120]
        # Force cleanup by advancing last_cleanup
        limiter._last_cleanup = time.monotonic() - 120
        # Next request triggers cleanup
        limiter.is_allowed("fresh-ip")
        assert "stale-ip" not in limiter._clients
        assert "fresh-ip" in limiter._clients

    def test_max_clients_cap(self) -> None:
        limiter = RateLimiter(requests_per_minute=5, max_clients=3)
        now = time.monotonic()
        # Add 5 clients with old-ish timestamps so they look stale
        for i in range(5):
            state = limiter._clients[f"ip-{i}"]
            state.timestamps = [now - 120]
        # Force cleanup on next call
        limiter._last_cleanup = now - 120
        limiter.is_allowed("fresh-ip")
        # All stale IPs evicted, only fresh-ip remains
        assert "fresh-ip" in limiter._clients
        assert len(limiter._clients) <= 3


class TestGetClientIp:
    """Unit tests for _get_client_ip helper."""

    def test_uses_rightmost_x_forwarded_for(self) -> None:
        request = MagicMock()
        request.headers = {"x-forwarded-for": "10.0.0.1, 172.16.0.1"}
        request.client = MagicMock(host="127.0.0.1")
        # Rightmost entry is from the nearest trusted proxy
        assert _get_client_ip(request) == "172.16.0.1"

    def test_falls_back_to_client_host(self) -> None:
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="192.168.1.1")
        assert _get_client_ip(request) == "192.168.1.1"

    def test_handles_no_client(self) -> None:
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert _get_client_ip(request) == "unknown"


class TestRateLimitMiddleware:
    """Integration tests for the RateLimitMiddleware."""

    @pytest.fixture()
    def rate_limited_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/api/health")
        async def health():
            return {"status": "ok"}

        @app.get("/api/data")
        async def data():
            return {"data": "value"}

        @app.get("/other")
        async def other():
            return {"other": True}

        limiter = RateLimiter(requests_per_minute=3)
        app.add_middleware(RateLimitMiddleware, rate_limiter=limiter)
        return app

    def test_health_endpoint_bypasses_rate_limit(self, rate_limited_app: FastAPI) -> None:
        client = TestClient(rate_limited_app)
        for _ in range(10):
            resp = client.get("/api/health")
            assert resp.status_code == 200

    def test_non_api_routes_bypass_rate_limit(self, rate_limited_app: FastAPI) -> None:
        client = TestClient(rate_limited_app)
        for _ in range(10):
            resp = client.get("/other")
            assert resp.status_code == 200

    def test_api_endpoints_are_rate_limited(self, rate_limited_app: FastAPI) -> None:
        client = TestClient(rate_limited_app)
        for _ in range(3):
            resp = client.get("/api/data")
            assert resp.status_code == 200
        resp = client.get("/api/data")
        assert resp.status_code == 429
        assert resp.json()["detail"] == "Rate limit exceeded. Try again later."

    def test_rate_limit_headers_present(self, rate_limited_app: FastAPI) -> None:
        client = TestClient(rate_limited_app)
        resp = client.get("/api/data")
        assert resp.status_code == 200
        assert resp.headers["x-ratelimit-limit"] == "3"
        assert resp.headers["x-ratelimit-remaining"] == "2"

    def test_429_response_includes_headers(self, rate_limited_app: FastAPI) -> None:
        client = TestClient(rate_limited_app)
        for _ in range(3):
            client.get("/api/data")
        resp = client.get("/api/data")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "60"
        assert resp.headers["x-ratelimit-remaining"] == "0"
