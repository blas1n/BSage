"""Phase Audit Batch 2 — raw aiosqlite outbox + relay unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bsvibe_audit import AuditActor, AuditDeliveryError, AuditResource
from bsvibe_audit.events.sage import KnowledgeEntryCreated, VaultFileModified

from bsage.garden.audit_outbox import (
    AiosqliteAuditOutbox,
    AiosqliteOutboxRelay,
    safe_emit,
)


@pytest.fixture()
async def outbox(tmp_path: Path):
    db_path = tmp_path / ".bsage" / "audit_outbox.db"
    o = AiosqliteAuditOutbox(db_path)
    await o.initialize()
    try:
        yield o
    finally:
        await o.close()


class TestOutboxInsertSelect:
    async def test_initialize_creates_db_and_table(self, tmp_path: Path) -> None:
        o = AiosqliteAuditOutbox(tmp_path / ".bsage" / "audit_outbox.db")
        await o.initialize()
        try:
            assert (tmp_path / ".bsage" / "audit_outbox.db").is_file()
            assert o.is_open is True
            # Empty table immediately after init.
            assert await o.count_pending() == 0
        finally:
            await o.close()

    async def test_insert_event_persists_payload(self, outbox: AiosqliteAuditOutbox) -> None:
        event = KnowledgeEntryCreated(
            actor=AuditActor(type="user", id="u-1", email="u1@example.com"),
            tenant_id="tenant-test",
            resource=AuditResource(type="knowledge_entry", id="note-id-1"),
            data={"title": "Hello", "tags": ["a"]},
        )
        row_id = await outbox.insert_event(event)
        assert row_id > 0

        rows = await outbox.select_undelivered(batch_size=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "sage.knowledge.entry_created"
        assert row["payload"]["tenant_id"] == "tenant-test"
        assert row["payload"]["data"]["title"] == "Hello"
        assert row["payload"]["resource"]["id"] == "note-id-1"

    async def test_mark_delivered_removes_from_undelivered(
        self, outbox: AiosqliteAuditOutbox
    ) -> None:
        event = VaultFileModified(
            actor=AuditActor(type="system", id="bsage"),
            resource=AuditResource(type="vault_file", id="ideas/x.md"),
            data={"operation": "garden_written"},
        )
        row_id = await outbox.insert_event(event)
        await outbox.mark_delivered([row_id])
        assert await outbox.count_pending() == 0

    async def test_record_failure_retryable_schedules_backoff(
        self, outbox: AiosqliteAuditOutbox
    ) -> None:
        event = VaultFileModified(
            actor=AuditActor(type="system", id="bsage"),
            data={"operation": "garden_written"},
        )
        row_id = await outbox.insert_event(event)

        await outbox.record_failure(row_id, error="boom", max_retries=5, retryable=True)
        # The row is still pending overall but invisible to the *now* poll
        # because next_attempt_at is in the future.
        rows = await outbox.select_undelivered(batch_size=10)
        assert rows == []
        assert await outbox.count_pending() == 1

    async def test_record_failure_non_retryable_dead_letters(
        self, outbox: AiosqliteAuditOutbox
    ) -> None:
        event = VaultFileModified(
            actor=AuditActor(type="system", id="bsage"),
            data={"operation": "garden_written"},
        )
        row_id = await outbox.insert_event(event)
        await outbox.record_failure(row_id, error="bad request", max_retries=5, retryable=False)
        # Permanently removed from select_undelivered AND count_pending.
        assert await outbox.count_pending() == 0


class TestSafeEmit:
    async def test_safe_emit_swallows_when_outbox_closed(self, tmp_path: Path) -> None:
        o = AiosqliteAuditOutbox(tmp_path / "audit.db")
        # Never call initialize() — is_open is False.
        event = VaultFileModified(
            actor=AuditActor(type="system", id="bsage"),
            data={"operation": "garden_written"},
        )
        # MUST NOT raise.
        await safe_emit(o, event)

    async def test_safe_emit_swallows_when_outbox_none(self) -> None:
        event = VaultFileModified(
            actor=AuditActor(type="system", id="bsage"),
            data={"operation": "garden_written"},
        )
        await safe_emit(None, event)

    async def test_safe_emit_swallows_internal_errors(
        self, outbox: AiosqliteAuditOutbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force insert_event to raise
        async def _boom(*_a, **_kw):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(outbox, "insert_event", _boom)

        event = VaultFileModified(
            actor=AuditActor(type="system", id="bsage"),
            data={"operation": "garden_written"},
        )
        # Must not propagate — sync API contract guard.
        await safe_emit(outbox, event)


class TestRelay:
    async def test_relay_disabled_when_no_client(self, outbox: AiosqliteAuditOutbox) -> None:
        relay = AiosqliteOutboxRelay(outbox=outbox, client=None, enabled=False)
        assert await relay.run_once() == 0
        await relay.start()  # no-op
        assert relay.is_running() is False
        await relay.stop()

    async def test_run_once_delivers_pending(self, outbox: AiosqliteAuditOutbox) -> None:
        # Seed two events
        for i in range(2):
            await outbox.insert_event(
                VaultFileModified(
                    actor=AuditActor(type="system", id="bsage"),
                    resource=AuditResource(type="vault_file", id=f"f{i}.md"),
                    data={"operation": "garden_written"},
                )
            )
        client = AsyncMock()
        relay = AiosqliteOutboxRelay(outbox=outbox, client=client, batch_size=10)

        delivered = await relay.run_once()
        assert delivered == 2
        client.send.assert_awaited_once()
        # All marked delivered
        assert await outbox.count_pending() == 0

    async def test_run_once_retryable_failure_records_backoff(
        self, outbox: AiosqliteAuditOutbox
    ) -> None:
        await outbox.insert_event(
            VaultFileModified(
                actor=AuditActor(type="system", id="bsage"),
                data={"operation": "garden_written"},
            )
        )
        client = AsyncMock()
        client.send.side_effect = AuditDeliveryError("503 down", retryable=True)
        relay = AiosqliteOutboxRelay(outbox=outbox, client=client, max_retries=5)

        delivered = await relay.run_once()
        assert delivered == 0
        # Still pending overall, but not eligible right now.
        assert await outbox.count_pending() == 1
        assert await outbox.select_undelivered(batch_size=10) == []

    async def test_run_once_non_retryable_dead_letters(self, outbox: AiosqliteAuditOutbox) -> None:
        await outbox.insert_event(
            VaultFileModified(
                actor=AuditActor(type="system", id="bsage"),
                data={"operation": "garden_written"},
            )
        )
        client = AsyncMock()
        client.send.side_effect = AuditDeliveryError("400 bad", retryable=False)
        relay = AiosqliteOutboxRelay(outbox=outbox, client=client)

        delivered = await relay.run_once()
        assert delivered == 0
        # Dead-lettered → no longer counted as pending.
        assert await outbox.count_pending() == 0
