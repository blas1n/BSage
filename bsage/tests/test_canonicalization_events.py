"""Tests for canonicalization event emission (Handoff §14)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from bsage.core.events import Event, EventBus, EventType
from bsage.garden.canonicalization.decisions import DecisionMemory
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.policies import PolicyResolver
from bsage.garden.canonicalization.resolver import TagResolver
from bsage.garden.canonicalization.service import CanonicalizationService
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage


class _Capture:
    """EventSubscriber that records every event for assertion."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def on_event(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self.events if e.event_type == event_type]


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path)


@pytest.fixture
def capture() -> _Capture:
    return _Capture()


@pytest.fixture
def event_bus(capture: _Capture) -> EventBus:
    bus = EventBus()
    bus.subscribe(capture)
    return bus


@pytest.fixture
async def service(storage: FileSystemStorage, event_bus: EventBus) -> CanonicalizationService:
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
    )


class TestEventTypeMembers:
    def test_nine_canonicalization_event_types_exist(self) -> None:
        # Per Handoff §14
        expected = {
            "CANONICALIZATION_PROPOSAL_CREATED",
            "CANONICALIZATION_PROPOSAL_STATUS_CHANGED",
            "CANONICALIZATION_ACTION_DRAFTED",
            "CANONICALIZATION_ACTION_STATUS_CHANGED",
            "CANONICALIZATION_ACTION_APPLIED",
            "CANONICALIZATION_DECISION_CREATED",
            "CANONICALIZATION_DECISION_SUPERSEDED",
            "CANONICALIZATION_POLICY_UPDATED",
            "CANONICALIZATION_POLICY_CONFLICT",
        }
        actual = {e.name for e in EventType if e.name.startswith("CANONICALIZATION_")}
        assert expected.issubset(actual)


class TestActionDraftedEvent:
    @pytest.mark.asyncio
    async def test_create_concept_draft_emits_event(
        self, service: CanonicalizationService, capture: _Capture
    ) -> None:
        path = await service.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        events = capture.of_type(EventType.CANONICALIZATION_ACTION_DRAFTED)
        assert len(events) == 1
        e = events[0]
        assert e.payload["path"] == path
        assert e.payload["status"] == "draft"
        assert e.payload["schema_version"] == "canonicalization-event-v1"


class TestActionAppliedEvent:
    @pytest.mark.asyncio
    async def test_apply_emits_action_applied(
        self, service: CanonicalizationService, capture: _Capture
    ) -> None:
        path = await service.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        await service.apply_action(path, actor="cli")

        applied = capture.of_type(EventType.CANONICALIZATION_ACTION_APPLIED)
        assert len(applied) == 1
        e = applied[0]
        assert e.payload["action_path"] == path
        assert e.payload["status"] == "applied"
        assert "concepts/active/ml.md" in e.payload["affected_paths"]
        assert e.payload["safe_mode"] is False
        # Status-changed event also fires (draft → applied)
        status_changes = capture.of_type(EventType.CANONICALIZATION_ACTION_STATUS_CHANGED)
        assert any(
            ev.payload.get("path") == path
            and ev.payload.get("status") == "applied"
            and ev.payload.get("previous_status") == "draft"
            for ev in status_changes
        )

    @pytest.mark.asyncio
    async def test_blocked_emits_status_changed_only(
        self, service: CanonicalizationService, capture: _Capture
    ) -> None:
        # First create a concept
        p1 = await service.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        await service.apply_action(p1, actor="cli")
        capture.events.clear()

        # Duplicate → blocked
        p2 = await service.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "Duplicate"}
        )
        await service.apply_action(p2, actor="cli")

        # No applied event
        assert capture.of_type(EventType.CANONICALIZATION_ACTION_APPLIED) == []
        status_changes = capture.of_type(EventType.CANONICALIZATION_ACTION_STATUS_CHANGED)
        assert any(
            ev.payload.get("status") == "blocked" and ev.payload.get("path") == p2
            for ev in status_changes
        )


class TestDecisionCreatedEvent:
    @pytest.mark.asyncio
    async def test_decision_apply_emits_decision_created(
        self, service: CanonicalizationService, capture: _Capture
    ) -> None:
        path = await service.create_action_draft(
            kind="create-decision",
            params={
                "decision_path": "decisions/cannot-link/20260507-140000-ci-cd.md",
                "subjects": ["ci", "cd"],
                "base_confidence": 0.95,
                "maturity": "seedling",
            },
        )
        await service.apply_action(path, actor="cli")
        created = capture.of_type(EventType.CANONICALIZATION_DECISION_CREATED)
        assert len(created) == 1
        e = created[0]
        assert e.payload["path"] == "decisions/cannot-link/20260507-140000-ci-cd.md"
        assert e.payload["kind"] == "cannot-link"
        assert e.payload["subjects"] == ["ci", "cd"]


class TestProposalEvents:
    @pytest.mark.asyncio
    async def test_accept_proposal_emits_status_change(
        self, service: CanonicalizationService, capture: _Capture, storage: FileSystemStorage
    ) -> None:
        # Setup proposal manually

        for c in ("self-hosting", "self-host"):
            p = await service.create_action_draft(
                kind="create-concept", params={"concept": c, "title": c}
            )
            await service.apply_action(p, actor="cli")

        from bsage.garden.canonicalization.proposals import DeterministicProposer

        proposer = DeterministicProposer(
            index=service._index,
            store=service._store,
            clock=lambda: datetime(2026, 5, 7, 14, 0, 0),
        )
        proposal_paths = await proposer.generate()
        assert len(proposal_paths) == 1
        capture.events.clear()

        await service.accept_proposal(proposal_paths[0], actor="cli")
        status_changes = capture.of_type(EventType.CANONICALIZATION_PROPOSAL_STATUS_CHANGED)
        assert any(
            ev.payload.get("path") == proposal_paths[0] and ev.payload.get("status") == "accepted"
            for ev in status_changes
        )


class TestPayloadShape:
    @pytest.mark.asyncio
    async def test_payload_is_path_oriented(
        self, service: CanonicalizationService, capture: _Capture
    ) -> None:
        # Per §14 — payloads MUST be small: paths, statuses, policy paths,
        # affected paths, short domain effects. No full notes inline.
        path = await service.create_action_draft(
            kind="create-concept", params={"concept": "ml", "title": "ML"}
        )
        await service.apply_action(path, actor="cli")

        for e in capture.events:
            payload_str = str(e.payload)
            # Heuristic: payload string should not exceed a few KB
            assert len(payload_str) < 4096, f"event payload too large: {e.event_type}"
            # No raw markdown body should be inlined
            assert "---\n" not in payload_str
