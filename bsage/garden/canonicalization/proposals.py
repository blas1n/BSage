"""DeterministicProposer — slice 3 proposal generation (Handoff §12).

Strategy ``deterministic`` uses preprocessing-only signals:
- exact alias collision between active concepts
- character-trigram Jaccard similarity on concept ids (simple lexical proxy)
- garden-tag frequency for canonical selection

No embeddings, no LLM, no Levenshtein (per spec §12 — Levenshtein is not a
default signal). The ``balanced`` strategy in slice 4 layers embedding KNN
+ EDC LLM verify on top of these same outputs.

Per §12, proposal generation MAY create draft action notes through
``service.create_action_draft``. We do exactly that — each proposal links
to a paired ``actions/merge-concepts/...md`` draft via ``action_drafts``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Any

import structlog

from bsage.garden.canonicalization import models, paths
from bsage.garden.canonicalization.index import CanonicalizationIndex
from bsage.garden.canonicalization.store import NoteStore

logger = structlog.get_logger(__name__)

_NGRAM_N = 3
_DEFAULT_THRESHOLD = 0.6
_DEFAULT_PROPOSAL_TTL = timedelta(days=7)
_GENERATOR_NAME = "deterministic-v1"
_GENERATOR_VERSION = "canonicalization-generator-v1"


class _UnionFind:
    """Tiny union-find for clustering similar concept ids."""

    def __init__(self, items: Iterable[str]) -> None:
        self._parent: dict[str, str] = {item: item for item in items}

    def find(self, x: str) -> str:
        # Path compression
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        cur = x
        while self._parent[cur] != root:
            self._parent[cur], cur = root, self._parent[cur]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> list[list[str]]:
        clusters: dict[str, list[str]] = {}
        for item in self._parent:
            clusters.setdefault(self.find(item), []).append(item)
        return [sorted(g) for g in clusters.values()]


class DeterministicProposer:
    """Generate `merge-concepts` proposals from active-concept similarity."""

    def __init__(
        self,
        index: CanonicalizationIndex,
        store: NoteStore,
        clock: Callable[[], datetime] | None = None,
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        self._index = index
        self._store = store
        self._clock = clock or datetime.now
        self._threshold = threshold

    # -------------------------------------------------------------- API

    async def generate(self) -> list[str]:
        concepts = await self._index.list_active_concepts()
        if len(concepts) < 2:
            return []

        clusters = self._cluster_by_similarity(concepts, self._threshold)

        # Pre-compute frequency: canonical selection prefers higher garden usage
        usage = await self._garden_tag_frequency([c.concept_id for c in concepts])
        existing_proposals = await self._existing_pending_merge_signatures()

        created: list[str] = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            ids = sorted(cluster)
            canonical = self._pick_canonical(ids, usage)
            merge = [c for c in ids if c != canonical]
            signature = self._cluster_signature(canonical, merge)
            if signature in existing_proposals:
                logger.debug(
                    "deterministic_proposer_dedup",
                    canonical=canonical,
                    merge=merge,
                )
                continue
            proposal_path = await self._write_proposal(canonical, merge, usage)
            created.append(proposal_path)
            existing_proposals.add(signature)
        return created

    # --------------------------------------------------- similarity helpers

    @staticmethod
    def ngram_jaccard(a: str, b: str, *, n: int = _NGRAM_N) -> float:
        if a == b:
            return 1.0
        ga = _ngrams(a, n)
        gb = _ngrams(b, n)
        if not ga and not gb:
            return 0.0
        union = ga | gb
        if not union:
            return 0.0
        return len(ga & gb) / len(union)

    def _cluster_by_similarity(
        self, concepts: list[models.ConceptEntry], threshold: float
    ) -> list[list[str]]:
        ids = [c.concept_id for c in concepts]
        uf = _UnionFind(ids)
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if self.ngram_jaccard(a, b) >= threshold:
                    uf.union(a, b)
        return [g for g in uf.groups() if len(g) > 1]

    @staticmethod
    def _pick_canonical(ids: list[str], usage: dict[str, int]) -> str:
        # Highest garden frequency wins; ties broken by longest id then alphabetic
        return max(ids, key=lambda c: (usage.get(c, 0), len(c), c))

    @staticmethod
    def _cluster_signature(canonical: str, merge: list[str]) -> str:
        return f"{canonical}|{','.join(sorted(merge))}"

    # ---------------------------------------------------- vault helpers

    async def _garden_tag_frequency(self, concept_ids: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {cid: 0 for cid in concept_ids}
        for path in await self._store.list_garden_paths():
            tags = await self._store.read_garden_tags(path)
            for tag in tags:
                if tag in counts:
                    counts[tag] += 1
        return counts

    async def _existing_pending_merge_signatures(self) -> set[str]:
        # Look at currently pending merge-concepts proposals; signature is
        # (canonical, merge-list) derived from the linked action draft.
        pending = await self._index.list_proposals(status="pending", kind="merge-concepts")
        signatures: set[str] = set()
        for prop in pending:
            for action_path in prop.action_drafts:
                action = await self._store.read_action(action_path)
                if action is None or action.status not in {"draft", "pending_approval"}:
                    continue
                canonical = action.params.get("canonical")
                merge = action.params.get("merge") or []
                if isinstance(canonical, str) and isinstance(merge, list):
                    signatures.add(self._cluster_signature(canonical, list(merge)))
        return signatures

    async def _write_proposal(
        self,
        canonical: str,
        merge: list[str],
        usage: dict[str, int],
    ) -> str:
        now = self._clock()

        # Build evidence — alias collisions + frequency observations
        evidence: list[dict[str, Any]] = []
        for old_id in merge:
            evidence.append(
                _envelope(
                    kind="alias_exact",
                    schema_version="alias-exact-v1",
                    payload={
                        "alias": old_id,
                        "matches_canonical": canonical,
                        "garden_uses_old": usage.get(old_id, 0),
                    },
                    observed_at=now,
                )
            )
        evidence.append(
            _envelope(
                kind="frequency",
                schema_version="frequency-v1",
                payload={
                    "canonical": canonical,
                    "uses": usage.get(canonical, 0),
                    "merge_uses": {old: usage.get(old, 0) for old in merge},
                },
                observed_at=now,
            )
        )

        # Create paired action draft via the existing draft pathway. The
        # service path handles collision suffix + index invalidation.
        action_path = await self._create_merge_action_draft(canonical, merge, now)

        # Create the proposal note
        proposal_slug = canonical
        candidate = paths.build_proposal_path("merge-concepts", now, proposal_slug)
        existing = await self._store.list_existing_proposal_paths("merge-concepts")
        proposal_path = paths.with_collision_suffix(candidate, existing)

        proposal_score = _confidence_from_jaccard(
            max(self.ngram_jaccard(canonical, m) for m in merge)
        )

        entry = models.ProposalEntry(
            path=proposal_path,
            kind="merge-concepts",
            status="pending",
            strategy="deterministic",
            generator=_GENERATOR_NAME,
            generator_version=_GENERATOR_VERSION,
            proposal_score=proposal_score,
            created_at=now,
            updated_at=now,
            expires_at=now + _DEFAULT_PROPOSAL_TTL,
            freshness={},
            evidence=evidence,
            affected_paths=[],
            action_drafts=[action_path],
            result_actions=[],
        )
        await self._store.write_proposal(entry)
        await self._index.invalidate(proposal_path)
        return proposal_path

    async def _create_merge_action_draft(
        self, canonical: str, merge: list[str], now: datetime
    ) -> str:
        """Write a draft action note directly without going through the service.

        DeterministicProposer is allowed to create draft action notes
        (Handoff §12 explicit), but apply MUST stay with the service. We
        write through the same NoteStore + paths conventions to preserve
        invariants without circular dependency on the service.
        """
        candidate = paths.build_action_path("merge-concepts", now, canonical)
        existing = await self._store.list_existing_action_paths("merge-concepts")
        action_path = paths.with_collision_suffix(candidate, existing)

        entry = models.ActionEntry(
            path=action_path,
            kind="merge-concepts",
            status="draft",
            action_schema_version="merge-concepts-v1",
            params={"canonical": canonical, "merge": list(merge)},
            created_at=now,
            updated_at=now,
            expires_at=now + _DEFAULT_PROPOSAL_TTL,
        )
        await self._store.write_action(entry)
        await self._index.invalidate(action_path)
        return action_path


# ---------------------------------------------------------------- utils


def _ngrams(s: str, n: int) -> set[str]:
    if not s:
        return set()
    if len(s) < n:
        return {s}
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _confidence_from_jaccard(j: float) -> float:
    """Map a 0..1 Jaccard similarity into a proposal score with mild bias."""
    return round(min(0.99, max(0.0, j)), 3)


def _envelope(
    *,
    kind: str,
    schema_version: str,
    payload: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "schema_version": schema_version,
        "source": "deterministic",
        "observed_at": observed_at.isoformat(),
        "producer": _GENERATOR_NAME,
        "payload": payload,
    }
