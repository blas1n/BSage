"""Tests for Safe Mode integration in canonicalization apply (Handoff §13 step 11).

The canonicalization layer is queue-based: when Safe Mode is ON, every
applied action persists as ``pending_approval`` and the reviewer picks
it up via the canon-queue UI (``approve_action`` / ``reject_action``
RPCs). There is no synchronous approver round-trip — see
:class:`bsage.core.safe_mode.ApprovalDeferred` for the rationale.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from bsage.core.events import EventBus, EventType
from bsage.core.safe_mode import ApprovalRequest
from bsage.garden.canonicalization.decisions import DecisionMemory
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.policies import PolicyResolver
from bsage.garden.canonicalization.resolver import TagResolver
from bsage.garden.canonicalization.service import CanonicalizationService
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.markdown_utils import extract_frontmatter
from bsage.garden.storage import FileSystemStorage


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path)


async def _make_service(
    storage: FileSystemStorage,
    *,
    safe_mode_on: bool,
    event_bus: EventBus | None = None,
) -> CanonicalizationService:
    fixed_now = datetime(2026, 5, 7, 14, 0, 0)
    index = InMemoryCanonicalizationIndex()
    await index.initialize(storage)
    store = NoteStore(storage)
    return CanonicalizationService(
        store=store,
        lock=AsyncIOMutationLock(),
        index=index,
        resolver=TagResolver(index=index),
        decisions=DecisionMemory(index=index, store=store),
        policies=PolicyResolver(index=index, store=store, clock=lambda: fixed_now),
        clock=lambda: fixed_now,
        event_bus=event_bus,
        safe_mode=lambda: safe_mode_on,
    )


class TestApprovalRequestExtension:
    def test_carries_action_metadata(self) -> None:
        # Per Handoff §13 — the request envelope (still used by the
        # plugin Safe Mode path via WebSocketApprovalInterface) carries
        # action_* fields so the frontend can render evidence.
        req = ApprovalRequest(
            skill_name="canonicalization",
            description="merge self-host into self-hosting",
            action_summary="apply merge-concepts",
            action_path="actions/merge-concepts/x.md",
            action_kind="merge-concepts",
            stability_score=0.9,
            risk_reasons=[],
            affected_paths=["concepts/active/self-hosting.md"],
        )
        assert req.action_path == "actions/merge-concepts/x.md"
        assert req.stability_score == 0.9


class TestSafeModeOff:
    @pytest.mark.asyncio
    async def test_off_means_auto_apply(self, storage: FileSystemStorage) -> None:
        svc = await _make_service(storage, safe_mode_on=False)
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        result = await svc.apply_action(path, actor="cli")
        assert result.final_status == "applied"


class TestSafeModeOn:
    @pytest.mark.asyncio
    async def test_on_yields_pending_approval(self, storage: FileSystemStorage) -> None:
        """Safe Mode ON ALWAYS parks the action in pending_approval —
        never auto-rejects, never tries to push for synchronous human
        consent. The reviewer pulls from the queue when they're online.
        """
        svc = await _make_service(storage, safe_mode_on=True)
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        result = await svc.apply_action(path, actor="cli")
        assert result.final_status == "pending_approval"
        fm = extract_frontmatter(await storage.read(path))
        assert fm["status"] == "pending_approval"
        assert fm["permission"]["safe_mode"] is True
        assert fm["permission"]["decision"] == "require_approval"

    @pytest.mark.asyncio
    async def test_pending_approval_emits_status_event(self, storage: FileSystemStorage) -> None:
        captured: list = []

        class _Cap:
            async def on_event(self, event):
                captured.append(event)

        bus = EventBus()
        bus.subscribe(_Cap())

        svc = await _make_service(storage, safe_mode_on=True, event_bus=bus)
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        await svc.apply_action(path, actor="cli")

        statuses = [
            e for e in captured if e.event_type == EventType.CANONICALIZATION_ACTION_STATUS_CHANGED
        ]
        assert any(ev.payload.get("status") == "pending_approval" for ev in statuses)


class TestApproveActionRpc:
    @pytest.mark.asyncio
    async def test_approve_action_applies(self, storage: FileSystemStorage) -> None:
        svc = await _make_service(storage, safe_mode_on=True)
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        first = await svc.apply_action(path, actor="cli")
        assert first.final_status == "pending_approval"

        approved = await svc.approve_action(path, actor="reviewer")
        assert approved.final_status == "applied"
        fm = extract_frontmatter(await storage.read(path))
        assert fm["status"] == "applied"
        assert fm["permission"]["decision"] == "approved"
        assert fm["permission"]["actor"] == "reviewer"

    @pytest.mark.asyncio
    async def test_reject_action_rpc(self, storage: FileSystemStorage) -> None:
        svc = await _make_service(storage, safe_mode_on=True)
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        await svc.apply_action(path, actor="cli")

        await svc.reject_action(path, actor="reviewer", reason="not now")
        # Re-applying a rejected action is a no-op (terminal status).
        result = await svc.apply_action(path, actor="cli")
        assert result.final_status == "rejected"
        fm = extract_frontmatter(await storage.read(path))
        assert fm["status"] == "rejected"
