"""Phase Audit Batch 2 — sync-API regression + emit verification.

These tests dogfood the exact contract the orchestrator's
``bsage-sync.sh`` relies on (the same payloads from
``test_sync_api_e2e_dogfooding.py``) but layer in audit emit
verification:

* Wiring an :class:`AiosqliteAuditOutbox` into ``state.audit_outbox`` and
  the ``GardenWriter`` must NOT change the 201 response shape.
* Each write triggers the corresponding ``sage.*`` event in the outbox.
* When the outbox raises mid-emit, the sync-API response still succeeds
  — the ``safe_emit`` guard must absorb the failure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.audit_outbox import AiosqliteAuditOutbox
from bsage.garden.ontology import OntologyRegistry
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.garden.writer_core import GardenWriter
from bsage.gateway.dependencies import AppState
from bsage.gateway.routes import create_routes


@pytest.fixture()
async def gateway_with_audit(tmp_path: Path):
    """Real GardenWriter + Vault + initialized AiosqliteAuditOutbox."""
    vault_root = tmp_path / "vault"
    Vault(vault_root).ensure_dirs()

    audit_db = tmp_path / ".bsage" / "audit_outbox.db"
    outbox = AiosqliteAuditOutbox(audit_db)
    await outbox.initialize()

    vault = Vault(vault_root)
    sync_manager = SyncManager()
    ontology = OntologyRegistry(vault_root / ".bsage" / "ontology.yaml")
    await ontology.load()
    writer = GardenWriter(
        vault=vault,
        sync_manager=sync_manager,
        ontology=ontology,
        audit_outbox=outbox,
    )

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
    state.audit_outbox = outbox

    async def _mock_get_current_user():
        return MagicMock(
            id="t-user",
            email="t@example.com",
            role="authenticated",
            active_tenant_id="tenant-test",
        )

    state.get_current_user = _mock_get_current_user
    state.auth_provider = None

    app = FastAPI()
    app.include_router(create_routes(state))

    try:
        yield TestClient(app), vault, writer, outbox
    finally:
        await outbox.close()


# ---------------------------------------------------------------------------
# 1. Sync-API contract must NOT regress when audit is wired
# ---------------------------------------------------------------------------


class TestSyncApiContractWithAuditWired:
    """The bsage-sync.sh wire shape MUST remain 201 + {id, path, created_at}."""

    def test_entry_returns_201_with_required_keys(self, gateway_with_audit) -> None:
        client, vault, _writer, _outbox = gateway_with_audit

        body = {
            "title": "Audit-wired entry",
            "content": "body content",
            "note_type": "reference",
            "tags": ["audit", "sprint-batch-2"],
            "source": "orchestrator",
        }
        resp = client.post("/api/knowledge/entries", json=body)
        assert resp.status_code == 201, resp.text
        created = resp.json()
        # Pinned wire keys
        assert {"id", "path", "created_at"}.issubset(created.keys())
        # File on disk
        assert (vault.root / created["path"]).is_file()

    def test_decision_returns_201_with_required_keys(self, gateway_with_audit) -> None:
        client, vault, _writer, _outbox = gateway_with_audit

        body = {
            "title": "Adopt outbox pattern",
            "decision": "Use raw aiosqlite outbox for BSage",
            "reasoning": "Stay aligned with Phase A Batch 5 raw-aiosqlite decision.",
            "alternatives": ["Adopt SQLAlchemy + alembic"],
            "context": "BSage write queue + raw aiosqlite are well established.",
            "tags": ["architecture"],
            "source": "orchestrator",
        }
        resp = client.post("/api/knowledge/decisions", json=body)
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert {"id", "path", "created_at"}.issubset(created.keys())
        assert (vault.root / created["path"]).is_file()


# ---------------------------------------------------------------------------
# 2. Audit emit verification — events land in the outbox after each write
# ---------------------------------------------------------------------------


class TestAuditEmitOnKnowledgeRoutes:
    def test_entry_emits_knowledge_entry_created(self, gateway_with_audit) -> None:
        client, _vault, _writer, outbox = gateway_with_audit
        body = {
            "title": "Emit test",
            "content": "audit body",
            "tags": ["x"],
            "source": "orchestrator",
        }
        resp = client.post("/api/knowledge/entries", json=body)
        assert resp.status_code == 201
        rows = asyncio.get_event_loop().run_until_complete(outbox.select_undelivered(batch_size=50))
        types = {r["event_type"] for r in rows}
        # write_garden emits sage.vault.file_modified, route emits
        # sage.knowledge.entry_created — both must be present.
        assert "sage.knowledge.entry_created" in types
        assert "sage.vault.file_modified" in types

        entry_event = next(r for r in rows if r["event_type"] == "sage.knowledge.entry_created")
        # actor maps from the principal
        assert entry_event["payload"]["actor"]["type"] == "user"
        assert entry_event["payload"]["actor"]["id"] == "t-user"
        # tenant follows the principal's active_tenant_id
        assert entry_event["payload"]["tenant_id"] == "tenant-test"
        # data pinned shape
        data = entry_event["payload"]["data"]
        assert data["title"] == "Emit test"
        assert data["tags"] == ["x"]
        assert "path" in data

    def test_decision_emits_decision_recorded(self, gateway_with_audit) -> None:
        client, _vault, _writer, outbox = gateway_with_audit
        body = {
            "title": "decision-x",
            "decision": "do X",
            "reasoning": "because",
            "alternatives": ["do Y"],
            "tags": [],
            "source": "orchestrator",
        }
        resp = client.post("/api/knowledge/decisions", json=body)
        assert resp.status_code == 201
        rows = asyncio.get_event_loop().run_until_complete(outbox.select_undelivered(batch_size=50))
        types = {r["event_type"] for r in rows}
        assert "sage.decision.recorded" in types
        # Note write also emits a vault file_modified event.
        assert "sage.vault.file_modified" in types

        rec = next(r for r in rows if r["event_type"] == "sage.decision.recorded")
        assert rec["payload"]["data"]["decision"] == "do X"
        assert rec["payload"]["data"]["alternatives"] == ["do Y"]


# ---------------------------------------------------------------------------
# 3. Audit failure must NOT break sync-API contract
# ---------------------------------------------------------------------------


class TestAuditFailureDoesNotBreakSyncApi:
    def test_entry_succeeds_when_outbox_insert_raises(
        self, gateway_with_audit, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, vault, _writer, outbox = gateway_with_audit

        async def _boom(*_a, **_kw):
            raise RuntimeError("audit DB exploded")

        monkeypatch.setattr(outbox, "insert_event", _boom)

        body = {
            "title": "Outbox down still 201",
            "content": "still works",
            "source": "orchestrator",
        }
        resp = client.post("/api/knowledge/entries", json=body)
        # safe_emit swallowed the failure — sync API contract preserved.
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert {"id", "path", "created_at"}.issubset(created.keys())
        assert (vault.root / created["path"]).is_file()


# ---------------------------------------------------------------------------
# 4. Vault file modified emit on update / delete
# ---------------------------------------------------------------------------


class TestWriterEmissionLifecycle:
    async def test_write_garden_emits_vault_file_modified(self, tmp_path: Path) -> None:
        from bsage.garden.note import GardenNote
        from bsage.garden.vault import Vault

        vault_root = tmp_path / "vault"
        Vault(vault_root).ensure_dirs()
        outbox = AiosqliteAuditOutbox(tmp_path / "audit.db")
        await outbox.initialize()
        try:
            writer = GardenWriter(vault=Vault(vault_root), audit_outbox=outbox)
            await writer.write_garden(
                GardenNote(
                    title="Phase Audit emit test",
                    content="hello",
                    note_type="idea",
                    source="unit-test",
                )
            )
            rows = await outbox.select_undelivered(batch_size=10)
            types = [r["event_type"] for r in rows]
            assert "sage.vault.file_modified" in types
            evt = next(r for r in rows if r["event_type"] == "sage.vault.file_modified")
            assert evt["payload"]["data"]["operation"] == "garden_written"
            assert evt["payload"]["data"]["note_type"] == "idea"
        finally:
            await outbox.close()

    async def test_update_note_emits_knowledge_entry_updated(self, tmp_path: Path) -> None:
        from bsage.garden.note import GardenNote
        from bsage.garden.vault import Vault

        vault_root = tmp_path / "vault"
        Vault(vault_root).ensure_dirs()
        outbox = AiosqliteAuditOutbox(tmp_path / "audit.db")
        await outbox.initialize()
        try:
            writer = GardenWriter(vault=Vault(vault_root), audit_outbox=outbox)
            written = await writer.write_garden(
                GardenNote(
                    title="UpdateMe",
                    content="v1",
                    note_type="idea",
                    source="unit-test",
                )
            )
            rel = str(written.relative_to(vault_root))
            await writer.update_note(rel, "v2 body", preserve_frontmatter=True)
            rows = await outbox.select_undelivered(batch_size=20)
            types = [r["event_type"] for r in rows]
            assert "sage.knowledge.entry_updated" in types
            assert "sage.vault.file_modified" in types
        finally:
            await outbox.close()

    async def test_seed_write_does_not_emit_knowledge_entry_updated(self, tmp_path: Path) -> None:
        """Seeds aren't knowledge entries — only vault.file_modified should fire."""
        from bsage.garden.vault import Vault

        vault_root = tmp_path / "vault"
        Vault(vault_root).ensure_dirs()
        outbox = AiosqliteAuditOutbox(tmp_path / "audit.db")
        await outbox.initialize()
        try:
            writer = GardenWriter(vault=Vault(vault_root), audit_outbox=outbox)
            await writer.write_seed("telegram", {"messages": ["hi"]})
            rows = await outbox.select_undelivered(batch_size=20)
            types = [r["event_type"] for r in rows]
            assert "sage.vault.file_modified" in types
            assert "sage.knowledge.entry_updated" not in types
            assert "sage.knowledge.entry_created" not in types
        finally:
            await outbox.close()
