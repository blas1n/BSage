"""Tests for /api/canonicalization/* REST routes (Handoff §15.1)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bsage.core.events import EventBus
from bsage.core.runtime_config import RuntimeConfig
from bsage.garden.canonicalization.decisions import DecisionMemory
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.policies import PolicyResolver
from bsage.garden.canonicalization.resolver import TagResolver
from bsage.garden.canonicalization.service import CanonicalizationService
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage
from bsage.gateway.canonicalization_routes import create_canonicalization_router


@pytest.fixture
async def state(tmp_path: Path):
    """Real AppState surface — but only the canonicalization fields wired."""
    storage = FileSystemStorage(tmp_path)
    index = InMemoryCanonicalizationIndex()
    await index.initialize(storage)
    store = NoteStore(storage)
    decisions = DecisionMemory(index=index, store=store)
    policies = PolicyResolver(
        index=index, store=store, clock=lambda: datetime(2026, 5, 7, 14, 0, 0)
    )
    await policies.bootstrap_defaults()

    bus = EventBus()
    state = MagicMock()
    state._canon_storage = storage
    state.canon_index = index
    state.canon_lock = AsyncIOMutationLock()
    state.canon_decisions = decisions
    state.canon_policies = policies
    state.runtime_config = RuntimeConfig(
        llm_model="",
        llm_api_key="",
        llm_api_base=None,
        safe_mode=False,
        disabled_entries=[],
    )
    state.canon_service = CanonicalizationService(
        store=store,
        lock=state.canon_lock,
        index=index,
        resolver=TagResolver(index=index),
        decisions=decisions,
        policies=policies,
        clock=lambda: datetime(2026, 5, 7, 14, 0, 0),
        event_bus=bus,
        safe_mode=lambda: state.runtime_config.safe_mode,
    )

    # Stub embedder/llm for balanced
    state.embedder = MagicMock(enabled=False)
    state.settings = MagicMock(llm_model="")
    state.llm_client = AsyncMock()

    async def _principal():
        return MagicMock(id="reviewer", name="reviewer")

    state.get_current_user = _principal
    return state


@pytest.fixture
def client(state):
    app = FastAPI()
    app.include_router(create_canonicalization_router(state))
    return TestClient(app)


def _create_concept_via_rest(client: TestClient, concept: str) -> str:
    res = client.post(
        "/api/canonicalization/actions/draft",
        json={
            "kind": "create-concept",
            "params": {"concept": concept, "title": concept},
        },
    )
    assert res.status_code == 200, res.text
    path = res.json()["path"]
    apply_res = client.post("/api/canonicalization/actions/apply", json={"action_path": path})
    assert apply_res.status_code == 200, apply_res.text
    assert apply_res.json()["final_status"] == "applied"
    return path


class TestConceptsEndpoint:
    def test_empty_active(self, client: TestClient) -> None:
        res = client.get("/api/canonicalization/concepts?status=active")
        assert res.status_code == 200
        assert res.json()["items"] == []

    def test_active_after_create(self, client: TestClient) -> None:
        _create_concept_via_rest(client, "ml")
        res = client.get("/api/canonicalization/concepts?status=active")
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["concept_id"] == "ml"


class TestActionsEndpoint:
    def test_draft_then_apply(self, client: TestClient, tmp_path: Path) -> None:
        path = _create_concept_via_rest(client, "ml")
        # GET /actions
        list_res = client.get("/api/canonicalization/actions?kind=create-concept")
        items = list_res.json()["items"]
        assert any(a["path"] == path and a["status"] == "applied" for a in items)

    def test_validate_then_score(self, client: TestClient) -> None:
        # Draft (don't apply)
        res = client.post(
            "/api/canonicalization/actions/draft",
            json={
                "kind": "create-concept",
                "params": {"concept": "ml", "title": "ML"},
            },
        )
        path = res.json()["path"]

        v = client.post("/api/canonicalization/actions/validate", json={"action_path": path})
        assert v.status_code == 200
        assert v.json()["status"] == "passed"

        s = client.post("/api/canonicalization/actions/score", json={"action_path": path})
        assert s.status_code == 200
        assert "stability_score" in s.json()
        assert "risk_reasons" in s.json()


class TestProposalsEndpoint:
    def test_generate_deterministic(self, client: TestClient) -> None:
        _create_concept_via_rest(client, "self-hosting")
        _create_concept_via_rest(client, "self-host")
        res = client.post(
            "/api/canonicalization/proposals/generate",
            json={"strategy": "deterministic"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["strategy"] == "deterministic"
        assert len(body["created"]) == 1
        # List
        listing = client.get("/api/canonicalization/proposals")
        items = listing.json()["items"]
        assert len(items) == 1
        assert items[0]["strategy"] == "deterministic"

    def test_generate_balanced_no_embedder_falls_back(self, client: TestClient) -> None:
        _create_concept_via_rest(client, "self-hosting")
        _create_concept_via_rest(client, "self-host")
        res = client.post("/api/canonicalization/proposals/generate", json={"strategy": "balanced"})
        # No embedder/verifier wired in test fixture → balanced falls back to
        # deterministic clustering, still produces the proposal with strategy
        # field set to 'balanced'.
        assert res.status_code == 200
        listing = client.get("/api/canonicalization/proposals")
        items = listing.json()["items"]
        assert any(p["strategy"] == "balanced" for p in items)


class TestApproveRejectEndpoints:
    def test_safe_mode_off_apply_direct(self, client: TestClient, state) -> None:
        # Default: safe_mode False → applies directly
        path = _create_concept_via_rest(client, "ml")
        # Re-apply should be idempotent
        res = client.post("/api/canonicalization/actions/apply", json={"action_path": path})
        assert res.json()["final_status"] == "applied"

    def test_safe_mode_on_yields_pending(self, client: TestClient, state) -> None:
        state.runtime_config.safe_mode = True
        # Draft + apply with safe mode on, no approval interface → pending
        res = client.post(
            "/api/canonicalization/actions/draft",
            json={"kind": "create-concept", "params": {"concept": "ml", "title": "ML"}},
        )
        path = res.json()["path"]
        apply_res = client.post("/api/canonicalization/actions/apply", json={"action_path": path})
        assert apply_res.json()["final_status"] == "pending_approval"

        # Approve via REST
        approve_res = client.post(
            "/api/canonicalization/actions/approve", json={"action_path": path}
        )
        assert approve_res.json()["final_status"] == "applied"

    def test_reject_via_rest(self, client: TestClient, state) -> None:
        state.runtime_config.safe_mode = True
        res = client.post(
            "/api/canonicalization/actions/draft",
            json={"kind": "create-concept", "params": {"concept": "ml", "title": "ML"}},
        )
        path = res.json()["path"]
        client.post("/api/canonicalization/actions/apply", json={"action_path": path})

        rej = client.post(
            "/api/canonicalization/actions/reject",
            json={"action_path": path, "reason": "not now"},
        )
        assert rej.status_code == 200
        assert rej.json()["final_status"] == "rejected"


class TestPoliciesEndpoint:
    def test_active_policies_listed(self, client: TestClient) -> None:
        res = client.get("/api/canonicalization/policies/active")
        assert res.status_code == 200
        items = res.json()["items"]
        kinds = {p["kind"] for p in items}
        # Bootstrap fixture loaded — three default policies
        assert kinds == {"staleness", "merge-auto-apply", "decision-maturity"}


class TestResolveTagEndpoint:
    def test_resolves_alias(self, client: TestClient) -> None:
        # Setup concept with an alias
        client.post(
            "/api/canonicalization/actions/draft",
            json={
                "kind": "create-concept",
                "params": {
                    "concept": "machine-learning",
                    "title": "ML",
                    "aliases": ["ml"],
                },
            },
        )
        # Apply
        listing = client.get("/api/canonicalization/actions?kind=create-concept")
        path = listing.json()["items"][0]["path"]
        client.post("/api/canonicalization/actions/apply", json={"action_path": path})

        res = client.post("/api/canonicalization/resolve-tag", json={"raw_tag": "ml"})
        assert res.status_code == 200
        assert res.json()["canonical"] == "machine-learning"


class TestNoteEndpoint:
    def test_get_note_round_trip(self, client: TestClient) -> None:
        path = _create_concept_via_rest(client, "ml")
        res = client.get(f"/api/canonicalization/note?path={path}")
        assert res.status_code == 200
        assert res.json()["path"] == path
        assert "applied" in res.json()["content"]

    def test_get_missing_returns_404(self, client: TestClient) -> None:
        res = client.get("/api/canonicalization/note?path=concepts/active/missing.md")
        assert res.status_code == 404

    def test_get_outside_canon_paths_400(self, client: TestClient) -> None:
        res = client.get("/api/canonicalization/note?path=garden/seedling/foo.md")
        assert res.status_code == 400
