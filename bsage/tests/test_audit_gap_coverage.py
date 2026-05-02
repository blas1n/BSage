"""Audit §6 BSage test gap coverage — Sprint 4.

The ecosystem audit (``BSVibe_Ecosystem_Audit.md §6``) called out three
test gaps for BSage. This file pins each one with a focused regression
test against the actual code path:

1. **Vault symlink attack** — ``Vault.resolve_path`` /
   ``Vault.read_note_content`` must refuse a path whose target is a
   symlink pointing outside the vault root, even if the symlink itself
   lives inside the vault.

2. **DangerAnalyzer LLM parsing failure** — when the LLM returns
   garbled or partial JSON (a real-world failure mode for local
   Ollama models we observed on qwen3-coder), the analyzer must
   default to ``is_dangerous=True`` and never raise out to the caller.

3. **Gateway ``/vault/file`` path traversal** — the HTTP endpoint
   must surface a ``400`` response (not crash, not 200 with content)
   for traversal attempts. Symlink escapes that the underlying
   ``Vault`` blocks must propagate as ``400`` too.

These tests are **regressions only**: they exercise real production
code paths through the same surface external callers / attackers
hit — no monkey-patching of the security primitives themselves.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.danger_analyzer import DangerAnalyzer
from bsage.core.exceptions import VaultPathError
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes

# ---------------------------------------------------------------------------
# 1. Vault symlink attack
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need elevated perms on Windows")
class TestVaultSymlinkAttack:
    """The audit calls out symlink escape as the BSage-specific traversal
    vector. The defense lives in ``Vault.resolve_path`` and
    ``Vault.read_note_content`` — both call ``Path.resolve()`` which
    follows symlinks before the ``is_relative_to`` boundary check.

    These tests verify the boundary holds for every plausible symlink
    shape: a single dangling link, a chained link, and an attempt to
    use the link as a *parent* of an otherwise-legitimate path.
    """

    def test_resolve_path_blocks_symlink_to_outside_via_subpath(self, tmp_path: Path) -> None:
        """A symlink inside the vault that points OUTSIDE the vault must
        be rejected when used as a subpath, even though the link file
        itself sits within the vault root."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("attacker payload")

        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        # Symlink lives inside the vault but resolves to outside.
        link = vault_root / "evil-link"
        link.symlink_to(outside)

        vault = Vault(vault_root)

        with pytest.raises(VaultPathError, match="traversal"):
            vault.resolve_path("evil-link/secret.md")

    def test_resolve_path_blocks_chained_symlink_escape(self, tmp_path: Path) -> None:
        """Chained symlinks (link_a → link_b → outside) must also
        resolve outside the boundary and be rejected."""
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "data.md"
        target.write_text("attacker payload")

        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        link_b = vault_root / "link-b"
        link_b.symlink_to(outside)
        link_a = vault_root / "link-a"
        link_a.symlink_to(link_b)

        vault = Vault(vault_root)

        with pytest.raises(VaultPathError, match="traversal"):
            vault.resolve_path("link-a/data.md")

    @pytest.mark.asyncio
    async def test_read_note_content_blocks_symlink_to_outside(self, tmp_path: Path) -> None:
        """``read_note_content`` is the pathway used by the gateway
        ``/vault/file`` endpoint — it must reject a vault-internal
        symlink that resolves to an outside file."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("attacker payload", encoding="utf-8")

        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        link = vault_root / "evil-link.md"
        link.symlink_to(outside / "secret.md")

        vault = Vault(vault_root)

        # The Path object the caller passes is INSIDE the vault on the
        # surface, but ``.resolve()`` follows the link to ``outside``.
        with pytest.raises(VaultPathError, match="traversal"):
            await vault.read_note_content(link)

    def test_resolve_path_allows_inside_symlink(self, tmp_path: Path) -> None:
        """Symlinks pointing to other locations *inside* the vault
        must still resolve cleanly — we only block escapes."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        actual_dir = vault_root / "ideas"
        actual_dir.mkdir()
        target = actual_dir / "real.md"
        target.write_text("real content")

        # Internal alias — entirely within the vault.
        alias = vault_root / "alias.md"
        alias.symlink_to(target)

        vault = Vault(vault_root)
        resolved = vault.resolve_path("alias.md")

        assert resolved.is_relative_to(vault_root.resolve())
        assert resolved.read_text() == "real content"


# ---------------------------------------------------------------------------
# 2. DangerAnalyzer LLM parsing failure
# ---------------------------------------------------------------------------


@pytest.fixture()
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "danger.json"


# Code that AST analysis CANNOT classify (deliberate syntax error) —
# forces the LLM fallback path that the audit calls out.
_AST_UNPARSEABLE = "def broken(:\n    pass\n"


class TestDangerAnalyzerLLMFailureModes:
    """Audit §6 — the LLM fallback must never explode out to the caller.

    Every malformed response shape we have observed in the wild
    (qwen3-coder dropping JSON, gpt-oss truncating at 4k, Ollama
    returning HTML 500 pages, etc.) must collapse to a conservative
    ``is_dangerous=True`` verdict with a human-readable reason.

    The existing test in ``test_danger_analyzer.py`` covers a single
    "not valid json" case; this class fans out across the realistic
    failure shapes — empty body, truncated JSON, wrong types,
    missing keys, raw exceptions — so future LLM provider changes
    cannot silently re-introduce the failure path.
    """

    async def test_llm_returns_empty_string(self, cache_path: Path) -> None:
        llm_fn = AsyncMock(return_value="")
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        is_dangerous, reason = await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        assert is_dangerous is True
        assert "LLM analysis failed" in reason

    async def test_llm_returns_truncated_json(self, cache_path: Path) -> None:
        llm_fn = AsyncMock(return_value='{"is_dangerous": tru')
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        is_dangerous, reason = await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        assert is_dangerous is True
        assert "LLM analysis failed" in reason

    async def test_llm_returns_html_error_page(self, cache_path: Path) -> None:
        """Real failure mode: Ollama returns a 500 HTML page on overload."""
        llm_fn = AsyncMock(return_value="<!DOCTYPE html><h1>500</h1>")
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        is_dangerous, _ = await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        assert is_dangerous is True

    async def test_llm_response_missing_is_dangerous_key(self, cache_path: Path) -> None:
        """JSON parses, but the contract field is missing — must not crash."""
        llm_fn = AsyncMock(return_value='{"reason": "I forgot the verdict"}')
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        is_dangerous, reason = await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        # KeyError on parse is caught by the broad except → defaults to dangerous.
        assert is_dangerous is True
        assert "LLM analysis failed" in reason

    async def test_llm_response_wrong_type_for_is_dangerous(self, cache_path: Path) -> None:
        """``is_dangerous`` is supposed to be a bool — a stringy
        response should still cast through ``bool(...)`` without
        crashing the caller."""
        llm_fn = AsyncMock(return_value='{"is_dangerous": "yes", "reason": "string verdict"}')
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)
        # bool("yes") is True — this should still produce a valid result, not raise.
        is_dangerous, reason = await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        assert isinstance(is_dangerous, bool)
        assert isinstance(reason, str)

    async def test_llm_callable_raises_exception(self, cache_path: Path) -> None:
        """The LLM transport itself can fail (network error, timeout).
        The analyzer must catch and default to dangerous."""

        async def _raise(_prompt: str) -> str:
            raise ConnectionError("ollama unreachable")

        analyzer = DangerAnalyzer(cache_path, llm_fn=_raise)
        is_dangerous, reason = await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        assert is_dangerous is True
        assert "ollama unreachable" in reason or "LLM analysis failed" in reason

    async def test_llm_fallback_verdict_is_cached(self, cache_path: Path) -> None:
        """Even the fallback (dangerous-by-default) must hit cache so
        we don't repeatedly call a flaky LLM for the same broken plugin."""
        llm_fn = AsyncMock(return_value="not json")
        analyzer = DangerAnalyzer(cache_path, llm_fn=llm_fn)

        await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")
        await analyzer.analyze("p", _AST_UNPARSEABLE, "desc")

        # Second call must NOT re-invoke the LLM.
        assert llm_fn.await_count == 1
        cached = json.loads(cache_path.read_text())
        assert cached["p"]["is_dangerous"] is True


# ---------------------------------------------------------------------------
# 3. Gateway /vault/file path traversal
# ---------------------------------------------------------------------------


def _build_state(tmp_path: Path, vault_root: Path) -> MagicMock:
    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.agent_loop = MagicMock()
    # Use the real Vault — we are testing the actual security boundary.
    state.vault = Vault(vault_root)
    state.runtime_config = RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.sync_manager = SyncManager()
    state.danger_map = {}
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    state.retriever = MagicMock()
    state.retriever.index_available = False
    state.chat_bridge = AsyncMock()
    state.chat_bridge.chat = AsyncMock(return_value="Mocked")
    state.prompt_registry = MagicMock(spec=PromptRegistry)

    async def _mock_get_current_user():
        return MagicMock(id="test-user", email="t@example.com", role="authenticated")

    state.get_current_user = _mock_get_current_user
    state.auth_provider = None
    return state


@pytest.fixture()
def vault_with_secret_outside(tmp_path: Path) -> tuple[Path, Path]:
    """Vault layout with a secret file *outside* the vault for traversal probes."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("ATTACKER_TARGET", encoding="utf-8")

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "real.md").write_text("# real\nlegit content\n", encoding="utf-8")

    return vault_root, outside


@pytest.fixture()
def gateway_client(tmp_path: Path, vault_with_secret_outside) -> TestClient:
    vault_root, _outside = vault_with_secret_outside
    state = _build_state(tmp_path, vault_root)
    app = FastAPI()
    app.include_router(create_routes(state))
    return TestClient(app)


class TestVaultFileEndpointTraversal:
    """Audit §6: ``GET /api/vault/file`` must refuse path traversal."""

    def test_dotdot_relative_traversal_returns_400(self, gateway_client: TestClient) -> None:
        resp = gateway_client.get("/api/vault/file", params={"path": "../outside/secret.txt"})
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_deep_dotdot_traversal_returns_400(self, gateway_client: TestClient) -> None:
        resp = gateway_client.get("/api/vault/file", params={"path": "../../../etc/passwd"})
        assert resp.status_code == 400

    def test_absolute_path_outside_vault_returns_400(self, gateway_client: TestClient) -> None:
        resp = gateway_client.get("/api/vault/file", params={"path": "/etc/passwd"})
        assert resp.status_code == 400

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks only")
    def test_symlink_escape_returns_400(
        self, gateway_client: TestClient, vault_with_secret_outside
    ) -> None:
        """Plant a symlink inside the vault that points outside, then
        try to fetch it via the API. The response MUST be 400 — not
        200 with the secret bytes."""
        vault_root, outside = vault_with_secret_outside
        link = vault_root / "evil.md"
        link.symlink_to(outside / "secret.txt")

        resp = gateway_client.get("/api/vault/file", params={"path": "evil.md"})
        assert resp.status_code == 400
        # And the secret content MUST NOT be on the wire.
        assert "ATTACKER_TARGET" not in resp.text

    def test_legit_path_still_works_under_real_vault(self, gateway_client: TestClient) -> None:
        """Negative regression: hardening must not break the happy path."""
        resp = gateway_client.get("/api/vault/file", params={"path": "real.md"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["path"] == "real.md"
        assert "legit content" in body["content"]

    def test_missing_file_returns_404_not_400(self, gateway_client: TestClient) -> None:
        """An in-vault path that simply doesn't exist must surface 404,
        not be misclassified as a traversal attempt."""
        resp = gateway_client.get("/api/vault/file", params={"path": "no-such-note.md"})
        assert resp.status_code == 404

    def test_empty_path_returns_validation_error(self, gateway_client: TestClient) -> None:
        """Missing query param → 422 from FastAPI, not 500."""
        resp = gateway_client.get("/api/vault/file")
        assert resp.status_code == 422

    def test_null_byte_in_path_does_not_crash(self, gateway_client: TestClient) -> None:
        """Null-byte injection (``%00``) historically bypassed naive
        path checks. The endpoint must reject it cleanly — either
        with 400 (boundary check) or 422 (validator) — never 500."""
        resp = gateway_client.get("/api/vault/file", params={"path": "real.md\x00../../etc/passwd"})
        assert resp.status_code in (400, 404, 422)
        # And the secret content MUST NOT be on the wire.
        assert "ATTACKER_TARGET" not in resp.text

    def test_directory_access_returns_404(
        self, gateway_client: TestClient, tmp_path: Path, vault_with_secret_outside
    ) -> None:
        """A path that resolves to a directory (not a file) must 404,
        not silently succeed and dump the directory listing."""
        vault_root, _ = vault_with_secret_outside
        (vault_root / "subdir").mkdir()

        resp = gateway_client.get("/api/vault/file", params={"path": "subdir"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _supports_symlinks() -> bool:
    """Skip helper for environments where unprivileged symlinks fail
    (uncommon outside Windows)."""
    return os.name != "nt"
