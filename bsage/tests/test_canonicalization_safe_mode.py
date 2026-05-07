"""Tests for Safe Mode integration in canonicalization apply (Handoff §13 step 11)."""

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


class _StubApproval:
    """Records ApprovalRequests and returns a configurable response."""

    def __init__(self, *, approve: bool) -> None:
        self.approve = approve
        self.requests: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> bool:
        self.requests.append(request)
        return self.approve


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path)


def _make_service(
    storage: FileSystemStorage,
    *,
    safe_mode_on: bool,
    approval: _StubApproval | None,
    event_bus: EventBus | None = None,
) -> CanonicalizationService:
    fixed_now = datetime(2026, 5, 7, 14, 0, 0)
    index = InMemoryCanonicalizationIndex()

    async def _init() -> None:
        await index.initialize(storage)

    import asyncio

    asyncio.get_event_loop().run_until_complete(_init())
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
        approval_interface=approval,
    )


@pytest.fixture
async def service_safe_off(storage: FileSystemStorage) -> CanonicalizationService:
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
        safe_mode=lambda: False,
    )


@pytest.fixture
async def service_safe_on_approve(
    storage: FileSystemStorage,
) -> tuple[CanonicalizationService, _StubApproval]:
    fixed_now = datetime(2026, 5, 7, 14, 0, 0)
    index = InMemoryCanonicalizationIndex()
    await index.initialize(storage)
    store = NoteStore(storage)
    approval = _StubApproval(approve=True)
    svc = CanonicalizationService(
        store=store,
        lock=AsyncIOMutationLock(),
        index=index,
        resolver=TagResolver(index=index),
        decisions=DecisionMemory(index=index, store=store),
        policies=PolicyResolver(index=index, store=store, clock=lambda: fixed_now),
        clock=lambda: fixed_now,
        safe_mode=lambda: True,
        approval_interface=approval,
    )
    return svc, approval


@pytest.fixture
async def service_safe_on_no_interface(
    storage: FileSystemStorage,
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
        safe_mode=lambda: True,
        approval_interface=None,
    )


class TestApprovalRequestExtension:
    def test_carries_action_metadata(self) -> None:
        # Per Handoff §13 — frontend needs action_path/kind/safe_mode/etc.
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
    async def test_off_means_auto_apply(
        self, service_safe_off: CanonicalizationService, storage: FileSystemStorage
    ) -> None:
        path = await service_safe_off.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        result = await service_safe_off.apply_action(path, actor="cli")
        assert result.final_status == "applied"


class TestSafeModeOn:
    @pytest.mark.asyncio
    async def test_on_with_approve_applies(
        self,
        service_safe_on_approve: tuple[CanonicalizationService, _StubApproval],
        storage: FileSystemStorage,
    ) -> None:
        svc, approval = service_safe_on_approve
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        result = await svc.apply_action(path, actor="cli")
        assert result.final_status == "applied"
        # Approval was requested with action metadata
        assert len(approval.requests) == 1
        req = approval.requests[0]
        assert req.action_path == path
        assert req.action_kind == "create-concept"
        # Permission record reflects approval
        fm = extract_frontmatter(await storage.read(path))
        assert fm["permission"]["safe_mode"] is True
        assert fm["permission"]["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_on_no_interface_yields_pending_approval(
        self,
        service_safe_on_no_interface: CanonicalizationService,
        storage: FileSystemStorage,
    ) -> None:
        path = await service_safe_on_no_interface.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        result = await service_safe_on_no_interface.apply_action(path, actor="cli")
        assert result.final_status == "pending_approval"
        fm = extract_frontmatter(await storage.read(path))
        assert fm["status"] == "pending_approval"

    @pytest.mark.asyncio
    async def test_on_with_reject_yields_rejected(self, storage: FileSystemStorage) -> None:
        fixed_now = datetime(2026, 5, 7, 14, 0, 0)
        index = InMemoryCanonicalizationIndex()
        await index.initialize(storage)
        store = NoteStore(storage)
        approval = _StubApproval(approve=False)
        svc = CanonicalizationService(
            store=store,
            lock=AsyncIOMutationLock(),
            index=index,
            resolver=TagResolver(index=index),
            decisions=DecisionMemory(index=index, store=store),
            policies=PolicyResolver(index=index, store=store, clock=lambda: fixed_now),
            clock=lambda: fixed_now,
            safe_mode=lambda: True,
            approval_interface=approval,
        )
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        result = await svc.apply_action(path, actor="cli")
        assert result.final_status == "rejected"
        fm = extract_frontmatter(await storage.read(path))
        assert fm["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_pending_approval_emits_status_event(self, storage: FileSystemStorage) -> None:
        fixed_now = datetime(2026, 5, 7, 14, 0, 0)
        index = InMemoryCanonicalizationIndex()
        await index.initialize(storage)
        store = NoteStore(storage)

        captured: list = []

        class _Cap:
            async def on_event(self, event):
                captured.append(event)

        bus = EventBus()
        bus.subscribe(_Cap())

        svc = CanonicalizationService(
            store=store,
            lock=AsyncIOMutationLock(),
            index=index,
            resolver=TagResolver(index=index),
            decisions=DecisionMemory(index=index, store=store),
            policies=PolicyResolver(index=index, store=store, clock=lambda: fixed_now),
            clock=lambda: fixed_now,
            safe_mode=lambda: True,
            approval_interface=None,
            event_bus=bus,
        )
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
    async def test_approve_action_applies(
        self, service_safe_on_no_interface: CanonicalizationService
    ) -> None:
        svc = service_safe_on_no_interface
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        # First apply leaves status=pending_approval
        first = await svc.apply_action(path, actor="cli")
        assert first.final_status == "pending_approval"

        # Approve via RPC
        approved = await svc.approve_action(path, actor="reviewer")
        assert approved.final_status == "applied"

    @pytest.mark.asyncio
    async def test_reject_action_rpc(
        self, service_safe_on_no_interface: CanonicalizationService
    ) -> None:
        svc = service_safe_on_no_interface
        path = await svc.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        await svc.apply_action(path, actor="cli")

        await svc.reject_action(path, actor="reviewer", reason="not now")
        # Now applying again should return rejected (terminal)
        result = await svc.apply_action(path, actor="cli")
        assert result.final_status == "rejected"
