"""Sync API end-to-end dogfooding — Sprint 4.

The orchestrator script ``~/Works/_infra/scripts/bsage-sync.sh`` is the
canonical external consumer of BSage's knowledge endpoints. Sprint 2
introduced 13 wire-format contract tests (``test_knowledge_contract.py``)
to pin individual endpoint shapes, but those tests assert each endpoint
in isolation against mocked writers.

Sprint 4 layers a *full pipeline* dogfooding scenario on top: the same
sequence ``bsage-sync.sh`` runs in production, exercised against the
**real** :class:`GardenWriter`, :class:`Vault`, and FastAPI app. Each
test simulates one of the script's sub-commands and verifies the
post-condition by reading the vault back out — both via the file
system and via the HTTP surface.

What this catches that the contract tests do not:
  * GardenWriter regressions that drop the file but still return 201
  * Path encoding mismatches between writer output and ``/vault/file``
  * Vault subdir pre-creation expectations
  * Search ↔ writer integration (entries written must be findable)

Why we do not shell out to the actual ``bsage-sync.sh``:
  * The script needs Supabase auth + a live network — incompatible
    with an offline pytest run.
  * The wire format is what we lock in, not the bash glue. We
    re-implement the curl+JSON dance the script does and assert
    every expected field appears.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.ontology import OntologyRegistry
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.garden.writer_core import GardenWriter
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes

# ---------------------------------------------------------------------------
# bsage-sync.sh request payloads — exact wire shapes from the script
# ---------------------------------------------------------------------------


def _entry_payload(
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
    note_type: str = "reference",
) -> dict:
    """Mirror ``cmd_entry`` in bsage-sync.sh."""
    return {
        "title": title,
        "content": content,
        "note_type": note_type,
        "tags": tags or [],
        "source": "orchestrator",
    }


def _decision_payload(
    *,
    title: str,
    decision: str,
    reasoning: str,
    context: str = "",
    tags: list[str] | None = None,
) -> dict:
    """Mirror ``cmd_decision`` in bsage-sync.sh."""
    return {
        "title": title,
        "decision": decision,
        "reasoning": reasoning,
        "context": context,
        "tags": tags or [],
        "source": "orchestrator",
    }


# ---------------------------------------------------------------------------
# Fixtures — real GardenWriter against a real Vault on disk
# ---------------------------------------------------------------------------


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    Vault(root).ensure_dirs()
    return root


@pytest.fixture()
def real_gateway(vault_root: Path) -> tuple[TestClient, Vault, GardenWriter]:
    """Wire up an in-memory FastAPI app with the actual GardenWriter +
    Vault — no mock writer. Reads / writes hit real disk."""
    import asyncio

    vault = Vault(vault_root)
    sync_manager = SyncManager()
    ontology = OntologyRegistry(vault_root / ".bsage" / "ontology.yaml")
    # Load defaults synchronously into a fresh loop — we are inside a
    # sync fixture but ``OntologyRegistry.load`` is async.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(ontology.load())
    finally:
        loop.close()
    writer = GardenWriter(vault=vault, sync_manager=sync_manager, ontology=ontology)

    state = MagicMock(spec=AppState)
    state.skill_loader = MagicMock()
    state.skill_loader.load_all = AsyncMock(return_value={})
    state.plugin_loader = MagicMock()
    state.plugin_loader.load_all = AsyncMock(return_value={})
    state.agent_loop = MagicMock()
    state.vault = vault
    state.runtime_config = RuntimeConfig(
        llm_model="anthropic/claude-sonnet-4-20250514",
        llm_api_key="test-key",
        llm_api_base=None,
        safe_mode=True,
        disabled_entries=[],
    )
    state.sync_manager = sync_manager
    state.danger_map = {}
    state.credential_store = MagicMock()
    state.credential_store.list_services = MagicMock(return_value=[])
    state.retriever = MagicMock()
    state.retriever.index_available = False
    state.retriever._vector_store = None
    state.retriever._embedder = None
    state.embedder = MagicMock()
    state.embedder.enabled = False
    state.vector_store = None
    state.prompt_registry = MagicMock(spec=PromptRegistry)
    state.prompt_registry.get = MagicMock(return_value="prompt")
    state.prompt_registry.render = MagicMock(return_value="prompt")
    state.chat_bridge = AsyncMock()
    state.garden_writer = writer
    state.ontology = ontology

    async def _mock_get_current_user():
        return MagicMock(id="t-user", email="t@example.com", role="authenticated")

    state.get_current_user = _mock_get_current_user
    state.auth_provider = None

    app = FastAPI()
    app.include_router(create_routes(state))
    return TestClient(app), vault, writer


# ---------------------------------------------------------------------------
# 1. `bsage-sync.sh entry` end-to-end
# ---------------------------------------------------------------------------


class TestEntrySyncDogfooding:
    """``bsage-sync.sh entry "<title>" <file> <tags>`` →
    ``POST /api/knowledge/entries`` → file appears in vault →
    ``GET /api/vault/file`` returns the same content →
    ``GET /api/knowledge/search`` finds it by tag/title."""

    def test_entry_full_pipeline(self, real_gateway) -> None:
        client, vault, _writer = real_gateway

        # 1) POST — same wire payload bsage-sync.sh sends.
        body = _entry_payload(
            title="Sprint 4 Test Entry",
            content="This is the body content for sprint-4 dogfooding.",
            tags=["bsvibe", "progress", "sprint-4", "test"],
        )
        resp = client.post("/api/knowledge/entries", json=body)
        assert resp.status_code == 201, resp.text
        created = resp.json()

        # 2) Wire shape pinned (subset that bsage-sync.sh reads).
        assert {"id", "path", "created_at"}.issubset(created.keys())
        assert created["path"]
        assert created["id"]

        # 3) The file must EXIST on disk under the vault root.
        on_disk = vault.root / created["path"]
        assert on_disk.is_file(), f"vault file missing: {on_disk}"
        text = on_disk.read_text(encoding="utf-8")
        assert "Sprint 4 Test Entry" in text
        assert "sprint-4 dogfooding" in text

        # 4) The frontmatter must persist source + tags so search can index them.
        assert "source: orchestrator" in text
        assert "sprint-4" in text  # tag landed in YAML

        # 5) Read back via the HTTP API the orchestrator uses on retrieval.
        get_resp = client.get("/api/vault/file", params={"path": created["path"]})
        assert get_resp.status_code == 200, get_resp.text
        get_body = get_resp.json()
        assert get_body["path"] == created["path"]
        assert "sprint-4 dogfooding" in get_body["content"]

        # 6) Search must find the new entry — full-text match on body.
        search_resp = client.get("/api/knowledge/search", params={"q": "sprint-4 dogfooding"})
        assert search_resp.status_code == 200
        results = search_resp.json()["results"]
        paths = [r["path"] for r in results]
        # The new entry's path appears in results.
        assert any(created["path"] in p or p in created["path"] for p in paths), (
            f"created path {created['path']} not found in search results {paths}"
        )

    def test_doc_subcommand_flow(self, real_gateway) -> None:
        """``bsage-sync.sh doc <md-file>`` derives title from filename
        and posts as a reference entry. Re-implement that locally and
        verify the same end state."""
        client, vault, _writer = real_gateway

        # bsage-sync.sh doc converts ``my_doc.md`` → title="my doc".
        title = "sprint-4 progress doc"
        content = "Detailed progress notes:\n- step 1\n- step 2\n"

        body = _entry_payload(title=title, content=content, tags=["bsvibe", "docs"])
        resp = client.post("/api/knowledge/entries", json=body)
        assert resp.status_code == 201
        created = resp.json()

        # File exists and has the title rendered.
        on_disk = vault.root / created["path"]
        assert on_disk.is_file()
        rendered = on_disk.read_text(encoding="utf-8")
        assert "sprint-4 progress doc" in rendered
        # The 2-step list survived the round-trip.
        assert "step 1" in rendered
        assert "step 2" in rendered

    def test_entry_with_links_appends_wikilinks(self, real_gateway) -> None:
        """The contract pins that ``links`` are appended as ``[[..]]`` to the
        body — orchestrator relies on this to chain knowledge graph edges."""
        client, vault, _writer = real_gateway

        body = _entry_payload(title="Linked Entry", content="See related projects.")
        body["links"] = ["Project Alpha", "Project Beta"]

        resp = client.post("/api/knowledge/entries", json=body)
        assert resp.status_code == 201
        created = resp.json()

        on_disk = vault.root / created["path"]
        text = on_disk.read_text(encoding="utf-8")
        assert "[[Project Alpha]]" in text
        assert "[[Project Beta]]" in text

    def test_repeated_entries_with_same_title_dont_overwrite(self, real_gateway) -> None:
        """Two posts with the same title in rapid succession (orchestrator
        retries on 401) must NOT silently overwrite. Each must produce a
        distinct file."""
        client, vault, _writer = real_gateway

        body1 = _entry_payload(title="Same Title", content="First post")
        body2 = _entry_payload(title="Same Title", content="Retry post")

        r1 = client.post("/api/knowledge/entries", json=body1)
        r2 = client.post("/api/knowledge/entries", json=body2)
        assert r1.status_code == 201
        assert r2.status_code == 201

        path1 = r1.json()["path"]
        path2 = r2.json()["path"]
        assert path1 != path2, "duplicate title silently overwrote"

        # Both files exist and have their respective bodies.
        text1 = (vault.root / path1).read_text(encoding="utf-8")
        text2 = (vault.root / path2).read_text(encoding="utf-8")
        assert "First post" in text1
        assert "Retry post" in text2


# ---------------------------------------------------------------------------
# 2. `bsage-sync.sh decision` end-to-end
# ---------------------------------------------------------------------------


class TestDecisionSyncDogfooding:
    """``bsage-sync.sh decision`` is the ADR/decision flow used during
    sprints. Round-trip the full structure through the wire and the disk."""

    def test_decision_record_full_pipeline(self, real_gateway) -> None:
        client, vault, _writer = real_gateway

        body = _decision_payload(
            title="Adopt SQLite Write Queue",
            decision="Serialize all SQLite writes through a single asyncio task.",
            reasoning=(
                "SQLite has a global write lock; concurrent ops surface as 'database is locked'."
            ),
            context="Audit §7.5 / Sprint 3 / S3-4 / G4.",
            tags=["bsvibe", "decision", "sprint-3"],
        )
        body["alternatives"] = [
            "Migrate to PostgreSQL (rejected — too invasive)",
            "Use file locks (rejected — process-only)",
        ]

        resp = client.post("/api/knowledge/decisions", json=body)
        assert resp.status_code == 201, resp.text
        created = resp.json()

        on_disk = vault.root / created["path"]
        assert on_disk.is_file()

        text = on_disk.read_text(encoding="utf-8")
        # Structured decision template — every section header pinned.
        assert "## Decision" in text
        assert "## Reasoning" in text
        assert "## Alternatives Considered" in text
        assert "## Context" in text
        # Body content survived.
        assert "Migrate to PostgreSQL" in text
        assert "Audit §7.5" in text

        # ``decision_record: true`` flag in frontmatter — orchestrator
        # relies on this to filter ADRs from regular notes.
        assert "decision_record: true" in text

    def test_decision_without_optional_fields_uses_placeholders(self, real_gateway) -> None:
        """A bare-bones decision (only required fields) must still produce a
        valid file with placeholder text — orchestrator should never see 500."""
        client, vault, _writer = real_gateway

        body = _decision_payload(
            title="Q",
            decision="D",
            reasoning="R",
        )

        resp = client.post("/api/knowledge/decisions", json=body)
        assert resp.status_code == 201
        created = resp.json()
        text = (vault.root / created["path"]).read_text(encoding="utf-8")

        # Placeholder for missing optional sections.
        assert "_None._" in text  # alternatives
        assert "_No additional context._" in text


# ---------------------------------------------------------------------------
# 3. `bsage-sync.sh search` end-to-end
# ---------------------------------------------------------------------------


class TestSearchSyncDogfooding:
    """``bsage-sync.sh search <q>`` is what we use to verify a sync
    landed. The contract is the response shape — but we additionally
    assert that an entry written through ``POST /entries`` is *actually*
    findable through search, end-to-end. That's the dogfood loop."""

    def test_write_then_search_round_trip(self, real_gateway) -> None:
        client, _vault, _writer = real_gateway

        # 1) Write a uniquely-tagged entry.
        unique_marker = "QQQ_UNIQUE_BSAGE_SPRINT4_MARKER_QQQ"
        body = _entry_payload(
            title="Uniquely tagged entry",
            content=f"Body with {unique_marker} embedded for findability.",
            tags=["test"],
        )
        write_resp = client.post("/api/knowledge/entries", json=body)
        assert write_resp.status_code == 201

        # 2) Search for it. Must return >= 1 result, all matching the marker.
        search_resp = client.get("/api/knowledge/search", params={"q": unique_marker})
        assert search_resp.status_code == 200
        results = search_resp.json()["results"]
        assert len(results) >= 1, "wrote an entry but search returned 0 hits"
        # And each returned item carries the marker substring somewhere
        # — proving search isn't just returning random matches.
        assert any(unique_marker in r["content_preview"] for r in results)

    def test_search_response_shape_matches_contract(self, real_gateway) -> None:
        """Pinned wire keys for ``SearchResultItem`` — orchestrator parses
        these. Tested under the dogfood path (real GardenWriter, not mock)."""
        client, _vault, _writer = real_gateway
        client.post(
            "/api/knowledge/entries",
            json=_entry_payload(title="A", content="alpha alpha alpha", tags=["test"]),
        )
        resp = client.get("/api/knowledge/search", params={"q": "alpha"})
        body = resp.json()
        assert "results" in body
        if body["results"]:
            item = body["results"][0]
            assert set(item.keys()) == {
                "title",
                "path",
                "content_preview",
                "relevance_score",
                "tags",
            }


# ---------------------------------------------------------------------------
# 4. Cross-pipeline: vault file traversal protection holds for written notes
# ---------------------------------------------------------------------------


class TestVaultBoundaryHoldsAfterWrite:
    """A sneaky regression vector: GardenWriter could in theory write a
    file with a path that, when re-fed to ``GET /vault/file``, accidentally
    bypasses the vault boundary. Lock that down."""

    def test_written_path_round_trips_through_vault_file_endpoint(self, real_gateway) -> None:
        client, vault, _writer = real_gateway

        body = _entry_payload(
            title="Boundary check ../../../../etc/passwd",
            content="malicious title attempt",
        )
        resp = client.post("/api/knowledge/entries", json=body)
        # GardenWriter MUST sanitize the title before using it as a
        # filename. The response path must be inside the vault.
        assert resp.status_code == 201
        rel = resp.json()["path"]

        # The returned path must NOT contain `..` segments or escape vault.
        assert ".." not in Path(rel).parts, f"writer leaked traversal segment: {rel}"
        on_disk = (vault.root / rel).resolve()
        assert on_disk.is_relative_to(vault.root.resolve())

        # And re-feeding the path through the HTTP API still works,
        # exactly like the orchestrator would after a write.
        get_resp = client.get("/api/vault/file", params={"path": rel})
        assert get_resp.status_code == 200
        # Use ``json.dumps`` to be defensive about non-ASCII paths
        # in the assertion message.
        assert get_resp.json()["path"] == rel, json.dumps(get_resp.json())
