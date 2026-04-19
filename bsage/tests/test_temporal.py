"""Tests for bi-temporal model and contradiction resolution."""

from __future__ import annotations

import pytest

from bsage.garden.contradiction import detect_and_resolve, detect_contradictions
from bsage.garden.graph_models import GraphEntity, GraphRelationship
from bsage.garden.storage import FileSystemStorage
from bsage.garden.vault_backend import VaultBackend


@pytest.fixture
async def backend(tmp_path):
    storage = FileSystemStorage(tmp_path / "vault")
    b = VaultBackend(storage)
    await b.initialize()
    yield b
    await b.close()


def _entity(name: str, etype: str = "person") -> GraphEntity:
    return GraphEntity(name=name, entity_type=etype, source_path="test.md")


def _rel(
    src_id: str,
    tgt_id: str,
    rtype: str = "works_at",
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> GraphRelationship:
    return GraphRelationship(
        source_id=src_id,
        target_id=tgt_id,
        rel_type=rtype,
        source_path="test.md",
        valid_from=valid_from,
        valid_to=valid_to,
    )


class TestBiTemporalModel:
    async def test_relationship_stores_temporal_fields(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme Corp", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)

        rel = _rel(id1, id2, valid_from="2024-01", valid_to="2025-06")
        await backend.upsert_relationship(rel)

        neighbors = await backend.query_neighbors(id1)
        assert len(neighbors) == 1
        r, _ = neighbors[0]
        assert r.valid_from == "2024-01"
        assert r.valid_to == "2025-06"
        assert r.recorded_at is not None

    async def test_query_valid_at(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme", etype="organization")
        e3 = _entity("NewCo", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)
        id3 = await backend.upsert_entity(e3)

        # Alice worked at Acme Jan 2024 - Jun 2025
        await backend.upsert_relationship(_rel(id1, id2, valid_from="2024-01", valid_to="2025-06"))
        # Alice works at NewCo from Jul 2025
        await backend.upsert_relationship(_rel(id1, id3, valid_from="2025-07"))

        # Query at 2024-06: should see Acme only
        results_2024 = await backend.query_valid_at(id1, "2024-06")
        names_2024 = {ent.name for _, ent in results_2024}
        assert "Acme" in names_2024
        assert "NewCo" not in names_2024

        # Query at 2025-08: should see NewCo only
        results_2025 = await backend.query_valid_at(id1, "2025-08")
        names_2025 = {ent.name for _, ent in results_2025}
        assert "NewCo" in names_2025
        assert "Acme" not in names_2025

    async def test_query_valid_at_no_temporal(self, backend):
        """Relationships without temporal fields are always valid."""
        e1 = _entity("Alice")
        e2 = _entity("Bob")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)
        await backend.upsert_relationship(_rel(id1, id2, rtype="knows"))

        results = await backend.query_valid_at(id1, "2026-01")
        assert len(results) == 1

    async def test_invalidate_relationship(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)

        rel = _rel(id1, id2, valid_from="2024-01")
        await backend.upsert_relationship(rel)

        ok = await backend.invalidate_relationship(rel.id, "2025-06")
        assert ok

        neighbors = await backend.query_neighbors(id1)
        r, _ = neighbors[0]
        assert r.valid_to == "2025-06"


class TestContradictionDetection:
    async def test_detect_contradiction(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme", etype="organization")
        e3 = _entity("NewCo", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)
        id3 = await backend.upsert_entity(e3)

        old_rel = _rel(id1, id2, valid_from="2024-01")
        await backend.upsert_relationship(old_rel)

        # Same person, same rel_type, different target → not a contradiction
        new_rel_diff_target = _rel(id1, id3, valid_from="2025-07")
        contras = await detect_contradictions(backend, new_rel_diff_target)
        assert len(contras) == 0

    async def test_detect_same_target_contradiction(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)

        old_rel = _rel(id1, id2, valid_from="2024-01")
        await backend.upsert_relationship(old_rel)

        # Same endpoints, same rel_type → contradiction
        new_rel = _rel(id1, id2, valid_from="2025-07")
        contras = await detect_contradictions(backend, new_rel)
        assert len(contras) == 1
        assert contras[0].id == old_rel.id

    async def test_no_contradiction_if_already_invalidated(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)

        old_rel = _rel(id1, id2, valid_from="2024-01", valid_to="2025-06")
        await backend.upsert_relationship(old_rel)

        new_rel = _rel(id1, id2, valid_from="2025-07")
        contras = await detect_contradictions(backend, new_rel)
        assert len(contras) == 0


class TestContradictionResolution:
    async def test_resolve_invalidates_older(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Acme", etype="organization")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)

        old_rel = _rel(id1, id2, valid_from="2024-01")
        await backend.upsert_relationship(old_rel)

        new_rel = _rel(id1, id2, valid_from="2025-07")
        await backend.upsert_relationship(new_rel)

        invalidated = await detect_and_resolve(backend, new_rel)
        assert old_rel.id in invalidated

        # Old relationship should now have valid_to set
        neighbors = await backend.query_neighbors(id1)
        for r, _ in neighbors:
            if r.id == old_rel.id:
                assert r.valid_to is not None

    async def test_resolve_no_contradictions(self, backend):
        e1 = _entity("Alice")
        e2 = _entity("Bob")
        id1 = await backend.upsert_entity(e1)
        id2 = await backend.upsert_entity(e2)

        rel = _rel(id1, id2, rtype="knows")
        await backend.upsert_relationship(rel)

        invalidated = await detect_and_resolve(backend, rel)
        assert invalidated == []
