"""Regression: canon index MUST skip legacy non-canon paths under shared
top-level dirs (Handoff §1).

The bug: ``actions/`` is shared between GardenWriter agent action log
(``actions/{YYYY-MM-DD}.md`` and ``actions/input-log/...``) and canon
typed actions (``actions/<kind>/<file>.md``). Slice-5 demo CI failed
because the demo seeder writes ``actions/2026-05-06_run.md`` and
``InMemoryCanonicalizationIndex.rebuild_from_vault`` raised
``ValueError: not an action path`` while walking that file, which
killed the FastAPI lifespan and made the gateway return socket-hangup
on every request.

Fix: filter to canon-shaped paths before calling NoteStore.read_*.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from bsage.garden.canonicalization import models
from bsage.garden.canonicalization.index import (
    InMemoryCanonicalizationIndex,
    _is_canon_action_path,
    _is_canon_decision_path,
    _is_canon_policy_path,
    _is_canon_proposal_path,
)
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path)


class TestCanonActionPathPredicate:
    @pytest.mark.parametrize(
        "path",
        [
            "actions/create-concept/20260507-140000-ml.md",
            "actions/merge-concepts/20260507-140000-self-hosting.md",
            "actions/retag-notes/20260507-140000-foo.md",
            "actions/create-decision/cannot-link/20260507-140000-ci-cd.md",
            "actions/create-decision/must-link/20260507-140000-auth.md",
        ],
    )
    def test_canon_paths_match(self, path: str) -> None:
        assert _is_canon_action_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            # Legacy GardenWriter daily action log — the demo crash trigger
            "actions/2026-05-06_run.md",
            "actions/2026-05-07.md",
            # Legacy input log
            "actions/input-log/2026-05-07.md",
            # Unknown kind
            "actions/refactor-concept/20260507-140000-x.md",
            # Missing decision-kind segment for create-decision
            "actions/create-decision/20260507-140000-x.md",
            # Wrong decision-kind
            "actions/create-decision/maybe-link/20260507-140000-x.md",
            # Non-md
            "actions/create-concept/sidecar.json",
            # Wrong root
            "concepts/active/ml.md",
        ],
    )
    def test_legacy_or_invalid_paths_rejected(self, path: str) -> None:
        assert not _is_canon_action_path(path)


class TestCanonProposalPathPredicate:
    def test_canon_path_matches(self) -> None:
        assert _is_canon_proposal_path("proposals/merge-concepts/20260507-140000-x.md")

    def test_unknown_kind_rejected(self) -> None:
        assert not _is_canon_proposal_path("proposals/random-kind/20260507-140000-x.md")


class TestCanonDecisionPathPredicate:
    def test_canon_path_matches(self) -> None:
        assert _is_canon_decision_path("decisions/cannot-link/20260507-140000-ci-cd.md")

    def test_policy_subpath_not_a_decision(self) -> None:
        # decisions/policy/... is the policy bucket, NOT a decision
        assert not _is_canon_decision_path("decisions/policy/staleness/conservative-default.md")


class TestCanonPolicyPathPredicate:
    def test_canon_path_matches(self) -> None:
        assert _is_canon_policy_path("decisions/policy/staleness/conservative-default.md")

    def test_unknown_policy_kind_rejected(self) -> None:
        assert not _is_canon_policy_path("decisions/policy/random-kind/x.md")


class TestRebuildSkipsLegacyActionLogs:
    @pytest.mark.asyncio
    async def test_rebuild_with_legacy_action_log_does_not_crash(
        self, storage: FileSystemStorage
    ) -> None:
        # Seed the legacy GardenWriter action log that crashed the demo
        await storage.write(
            "actions/2026-05-06_run.md",
            "# Action log for 2026-05-06\n\n* 14:30 — calendar-input completed\n",
        )
        await storage.write(
            "actions/input-log/2026-05-06.md",
            "# Input log for 2026-05-06\n\n* raw input ...\n",
        )

        # Also seed a real canon action so we can verify it IS picked up
        store = NoteStore(storage)
        canon_action_path = "actions/create-concept/20260507-140000-ml.md"
        await store.write_action(
            models.ActionEntry(
                path=canon_action_path,
                kind="create-concept",
                status="draft",
                action_schema_version="create-concept-v1",
                params={"concept": "ml", "title": "ML"},
                created_at=datetime(2026, 5, 7),
                updated_at=datetime(2026, 5, 7),
                expires_at=datetime(2026, 5, 8),
            )
        )

        # rebuild_from_vault MUST NOT raise on the legacy log
        index = InMemoryCanonicalizationIndex()
        await index.initialize(storage)  # calls rebuild_from_vault under the hood

        # Canon action indexed
        actions = await index.list_actions(kind="create-concept")
        assert len(actions) == 1
        assert actions[0].path == canon_action_path

        # Legacy log NOT indexed
        all_actions = await index.list_actions()
        assert all("2026-05-06_run" not in a.path for a in all_actions)
        assert all("input-log" not in a.path for a in all_actions)

    @pytest.mark.asyncio
    async def test_invalidate_on_legacy_path_is_noop(self, storage: FileSystemStorage) -> None:
        index = InMemoryCanonicalizationIndex()
        await index.initialize(storage)
        # Should NOT raise — predicate filter kicks in before read_action
        await index.invalidate("actions/2026-05-06_run.md")
        await index.invalidate("actions/input-log/2026-05-06.md")
        await index.invalidate("decisions/random-stuff.md")
        # Canon listings remain empty
        assert await index.list_actions() == []
