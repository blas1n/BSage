"""Tests for GraphStore — real SQLite via tmp_path."""

import asyncio

import pytest

from bsage.garden.graph_models import GraphEntity, GraphRelationship, ProvenanceRecord
from bsage.garden.graph_store import GraphStore


@pytest.fixture
async def store(tmp_path):
    db_path = tmp_path / ".bsage" / "graph.db"
    gs = GraphStore(db_path)
    await gs.initialize()
    yield gs
    await gs.close()


# ------------------------------------------------------------------
# Entity CRUD
# ------------------------------------------------------------------


async def test_upsert_entity_insert(store: GraphStore):
    e = GraphEntity(name="BSage", entity_type="project", source_path="garden/idea/bsage.md")
    eid = await store.upsert_entity(e)
    assert eid == e.id
    assert await store.count_entities() == 1


async def test_upsert_entity_dedup(store: GraphStore):
    """Same (name_normalized, entity_type) returns existing ID."""
    e1 = GraphEntity(name="BSage", entity_type="project", source_path="a.md")
    e2 = GraphEntity(name="bsage", entity_type="project", source_path="b.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)
    assert id1 == id2
    assert await store.count_entities() == 1


async def test_upsert_entity_different_types_not_dedup(store: GraphStore):
    """Same name but different types are separate entities."""
    e1 = GraphEntity(name="Python", entity_type="tool", source_path="a.md")
    e2 = GraphEntity(name="Python", entity_type="concept", source_path="a.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)
    assert id1 != id2
    assert await store.count_entities() == 2


async def test_upsert_entity_updates_properties(store: GraphStore):
    """Upserting existing entity updates source_path, properties, confidence."""
    e1 = GraphEntity(
        name="Alice", entity_type="person", source_path="a.md", properties={"role": "dev"}
    )
    await store.upsert_entity(e1)

    e2 = GraphEntity(
        name="alice",
        entity_type="person",
        source_path="b.md",
        properties={"role": "lead"},
        confidence=0.9,
    )
    await store.upsert_entity(e2)

    found = await store.get_entity_by_name("Alice", "person")
    assert found is not None
    assert found.source_path == "b.md"
    assert found.properties["role"] == "lead"
    assert found.confidence == 0.9


# ------------------------------------------------------------------
# Relationship CRUD
# ------------------------------------------------------------------


async def test_upsert_relationship(store: GraphStore):
    e1 = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    e2 = GraphEntity(name="B", entity_type="concept", source_path="a.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)

    rel = GraphRelationship(source_id=id1, target_id=id2, rel_type="related_to", source_path="a.md")
    rid = await store.upsert_relationship(rel)
    assert rid == rel.id
    assert await store.count_relationships() == 1


async def test_upsert_relationship_dedup(store: GraphStore):
    """Same (source_id, target_id, rel_type) skips duplicate."""
    e1 = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    e2 = GraphEntity(name="B", entity_type="concept", source_path="a.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)

    r1 = GraphRelationship(source_id=id1, target_id=id2, rel_type="related_to", source_path="a.md")
    r2 = GraphRelationship(source_id=id1, target_id=id2, rel_type="related_to", source_path="b.md")
    rid1 = await store.upsert_relationship(r1)
    rid2 = await store.upsert_relationship(r2)
    assert rid1 == rid2
    assert await store.count_relationships() == 1


# ------------------------------------------------------------------
# Delete by source
# ------------------------------------------------------------------


async def test_delete_by_source(store: GraphStore):
    e1 = GraphEntity(name="X", entity_type="concept", source_path="note.md")
    e2 = GraphEntity(name="Y", entity_type="concept", source_path="note.md")
    e3 = GraphEntity(name="Z", entity_type="concept", source_path="other.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)
    await store.upsert_entity(e3)

    rel = GraphRelationship(
        source_id=id1, target_id=id2, rel_type="related_to", source_path="note.md"
    )
    await store.upsert_relationship(rel)

    deleted = await store.delete_by_source("note.md")
    assert deleted == 2
    assert await store.count_entities() == 1  # only Z remains
    assert await store.count_relationships() == 0


# ------------------------------------------------------------------
# Queries
# ------------------------------------------------------------------


async def test_get_entity_by_name(store: GraphStore):
    e = GraphEntity(name="BSage", entity_type="project", source_path="a.md")
    await store.upsert_entity(e)

    found = await store.get_entity_by_name("bsage")
    assert found is not None
    assert found.name == "BSage"

    found_typed = await store.get_entity_by_name("bsage", "project")
    assert found_typed is not None

    not_found = await store.get_entity_by_name("bsage", "person")
    assert not_found is None


async def test_search_entities(store: GraphStore):
    for name in ["Python", "PyTorch", "JavaScript"]:
        await store.upsert_entity(GraphEntity(name=name, entity_type="tool", source_path="a.md"))

    results = await store.search_entities("py")
    assert len(results) == 2
    names = {e.name for e in results}
    assert names == {"Python", "PyTorch"}


async def test_query_neighbors(store: GraphStore):
    e1 = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    e2 = GraphEntity(name="B", entity_type="concept", source_path="a.md")
    e3 = GraphEntity(name="C", entity_type="concept", source_path="a.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)
    id3 = await store.upsert_entity(e3)

    await store.upsert_relationship(
        GraphRelationship(source_id=id1, target_id=id2, rel_type="related_to", source_path="a.md")
    )
    await store.upsert_relationship(
        GraphRelationship(source_id=id3, target_id=id1, rel_type="uses", source_path="a.md")
    )

    # A has two neighbors: B (outgoing) and C (incoming)
    neighbors = await store.query_neighbors(id1)
    assert len(neighbors) == 2
    neighbor_names = {ent.name for _, ent in neighbors}
    assert neighbor_names == {"B", "C"}


async def test_query_neighbors_filter_by_type(store: GraphStore):
    e1 = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    e2 = GraphEntity(name="B", entity_type="concept", source_path="a.md")
    e3 = GraphEntity(name="C", entity_type="concept", source_path="a.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)
    id3 = await store.upsert_entity(e3)

    await store.upsert_relationship(
        GraphRelationship(source_id=id1, target_id=id2, rel_type="related_to", source_path="a.md")
    )
    await store.upsert_relationship(
        GraphRelationship(source_id=id1, target_id=id3, rel_type="uses", source_path="a.md")
    )

    neighbors = await store.query_neighbors(id1, rel_type="uses")
    assert len(neighbors) == 1
    assert neighbors[0][1].name == "C"


async def test_multi_hop_query(store: GraphStore):
    # A -> B -> C (chain of 2 hops)
    ea = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    eb = GraphEntity(name="B", entity_type="concept", source_path="a.md")
    ec = GraphEntity(name="C", entity_type="concept", source_path="a.md")
    id_a = await store.upsert_entity(ea)
    id_b = await store.upsert_entity(eb)
    id_c = await store.upsert_entity(ec)

    await store.upsert_relationship(
        GraphRelationship(source_id=id_a, target_id=id_b, rel_type="related_to", source_path="a.md")
    )
    await store.upsert_relationship(
        GraphRelationship(source_id=id_b, target_id=id_c, rel_type="related_to", source_path="a.md")
    )

    results = await store.multi_hop_query(id_a, max_hops=2)
    assert len(results) == 2
    assert results[0] == (1, eb)  # depth 1: B
    assert results[1][0] == 2  # depth 2: C
    assert results[1][1].name == "C"


async def test_multi_hop_query_no_cycles(store: GraphStore):
    """BFS does not revisit nodes in a cycle."""
    ea = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    eb = GraphEntity(name="B", entity_type="concept", source_path="a.md")
    id_a = await store.upsert_entity(ea)
    id_b = await store.upsert_entity(eb)

    # A <-> B (bidirectional)
    await store.upsert_relationship(
        GraphRelationship(source_id=id_a, target_id=id_b, rel_type="related_to", source_path="a.md")
    )
    await store.upsert_relationship(
        GraphRelationship(source_id=id_b, target_id=id_a, rel_type="related_to", source_path="a.md")
    )

    results = await store.multi_hop_query(id_a, max_hops=3)
    assert len(results) == 1  # only B, no revisiting A


# ------------------------------------------------------------------
# Provenance
# ------------------------------------------------------------------


async def test_add_provenance(store: GraphStore):
    e = GraphEntity(name="Test", entity_type="concept", source_path="a.md")
    eid = await store.upsert_entity(e)

    record = ProvenanceRecord(
        entity_id=eid,
        source_path="a.md",
        extraction_method="rule",
        confidence=1.0,
        extracted_at="2026-03-12T00:00:00Z",
    )
    await store.add_provenance(record)

    row = await store._fetchone("SELECT COUNT(*) FROM provenance WHERE entity_id = ?", (eid,))
    assert row[0] == 1


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


async def test_not_initialized():
    gs = GraphStore(__import__("pathlib").Path("/tmp/nonexistent.db"))
    with pytest.raises(RuntimeError, match="not initialized"):
        await gs.upsert_entity(GraphEntity(name="X", entity_type="concept", source_path="a.md"))


async def test_search_entities_empty(store: GraphStore):
    results = await store.search_entities("nonexistent")
    assert results == []


async def test_delete_by_source_no_match(store: GraphStore):
    deleted = await store.delete_by_source("no-such-file.md")
    assert deleted == 0


# ------------------------------------------------------------------
# Concurrency / write lock tests
# ------------------------------------------------------------------


async def test_concurrent_upsert_entities(store: GraphStore):
    """Concurrent upsert calls should not lose data thanks to write lock."""
    entities = [
        GraphEntity(name=f"Entity{i}", entity_type="concept", source_path=f"n{i}.md")
        for i in range(20)
    ]

    await asyncio.gather(*(store.upsert_entity(e) for e in entities))

    count = await store.count_entities()
    assert count == 20


async def test_concurrent_read_during_write(store: GraphStore):
    """Reads should work concurrently with writes (WAL mode)."""
    e = GraphEntity(name="Alpha", entity_type="concept", source_path="a.md")
    await store.upsert_entity(e)
    await store.commit()

    async def _read():
        return await store.search_entities("alpha")

    async def _write():
        for i in range(5):
            e2 = GraphEntity(name=f"Beta{i}", entity_type="concept", source_path=f"b{i}.md")
            await store.upsert_entity(e2)
        await store.commit()

    results = await asyncio.gather(_read(), _write())
    # Read should return at least Alpha
    assert len(results[0]) >= 1


# ------------------------------------------------------------------
# Maturity-related queries
# ------------------------------------------------------------------


async def test_count_relationships_for_entity(store: GraphStore):
    e1 = GraphEntity(name="NoteA", entity_type="note", source_path="garden/idea/a.md")
    e2 = GraphEntity(name="Concept1", entity_type="concept", source_path="garden/idea/a.md")
    e3 = GraphEntity(name="Concept2", entity_type="concept", source_path="garden/idea/b.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)
    id3 = await store.upsert_entity(e3)

    r1 = GraphRelationship(source_id=id1, target_id=id2, rel_type="references", source_path="a.md")
    r2 = GraphRelationship(source_id=id3, target_id=id1, rel_type="related_to", source_path="b.md")
    await store.upsert_relationship(r1)
    await store.upsert_relationship(r2)
    await store.commit()

    # NoteA and Concept1 share source_path "garden/idea/a.md"
    # r1: NoteA→Concept1 (both in a.md), r2: Concept2→NoteA (NoteA in a.md)
    # Should count exactly 2 distinct relationships, not double-count
    count = await store.count_relationships_for_entity("garden/idea/a.md")
    assert count == 2


async def test_count_relationships_for_entity_zero(store: GraphStore):
    e = GraphEntity(name="Lonely", entity_type="note", source_path="garden/idea/lonely.md")
    await store.upsert_entity(e)
    await store.commit()

    count = await store.count_relationships_for_entity("garden/idea/lonely.md")
    assert count == 0


async def test_count_distinct_sources(store: GraphStore):
    e = GraphEntity(name="Multi", entity_type="concept", source_path="a.md")
    eid = await store.upsert_entity(e)

    p1 = ProvenanceRecord(
        entity_id=eid,
        source_path="a.md",
        extraction_method="rule",
        confidence=1.0,
        extracted_at="2026-01-01T00:00:00",
    )
    p2 = ProvenanceRecord(
        entity_id=eid,
        source_path="b.md",
        extraction_method="rule",
        confidence=1.0,
        extracted_at="2026-01-01T00:00:00",
    )
    await store.add_provenance(p1)
    await store.add_provenance(p2)
    await store.commit()

    count = await store.count_distinct_sources("a.md")
    assert count >= 1


async def test_count_distinct_sources_zero(store: GraphStore):
    count = await store.count_distinct_sources("nonexistent.md")
    assert count == 0


async def test_get_entity_updated_at(store: GraphStore):
    e = GraphEntity(name="Timed", entity_type="note", source_path="garden/idea/timed.md")
    await store.upsert_entity(e)
    await store.commit()

    ts = await store.get_entity_updated_at("garden/idea/timed.md")
    assert ts is not None


async def test_get_entity_updated_at_missing(store: GraphStore):
    ts = await store.get_entity_updated_at("nonexistent.md")
    assert ts is None


# ------------------------------------------------------------------
# count_entities_of_type
# ------------------------------------------------------------------


async def test_count_relationships_for_entity_fallback_normalized(store: GraphStore):
    """Fallback to normalized name when source_path doesn't match."""
    e1 = GraphEntity(name="FallbackEntity", entity_type="concept", source_path="x.md")
    e2 = GraphEntity(name="Other", entity_type="concept", source_path="y.md")
    id1 = await store.upsert_entity(e1)
    id2 = await store.upsert_entity(e2)

    await store.upsert_relationship(
        GraphRelationship(source_id=id1, target_id=id2, rel_type="references", source_path="x.md")
    )
    await store.commit()

    # Query by entity name (not source_path) — triggers fallback
    count = await store.count_relationships_for_entity("FallbackEntity")
    assert count >= 1


async def test_count_distinct_sources_fallback_normalized(store: GraphStore):
    """Fallback to normalized name when source_path doesn't match."""
    e = GraphEntity(name="SourcedConcept", entity_type="concept", source_path="z.md")
    eid = await store.upsert_entity(e)

    p = ProvenanceRecord(
        entity_id=eid,
        source_path="z.md",
        extraction_method="rule",
        confidence=1.0,
        extracted_at="2026-01-01T00:00:00",
    )
    await store.add_provenance(p)
    await store.commit()

    # Query by entity name, not the actual source_path — triggers fallback
    count = await store.count_distinct_sources("SourcedConcept")
    assert count >= 1


async def test_get_entity_updated_at_fallback_normalized(store: GraphStore):
    """Fallback to normalized name when source_path doesn't match."""
    e = GraphEntity(name="TimedConcept", entity_type="concept", source_path="abc.md")
    await store.upsert_entity(e)
    await store.commit()

    # Query by name, not source_path — triggers fallback
    ts = await store.get_entity_updated_at("TimedConcept")
    assert ts is not None


async def test_count_entities_of_type(store: GraphStore):
    await store.upsert_entity(GraphEntity(name="A", entity_type="idea", source_path="a.md"))
    await store.upsert_entity(GraphEntity(name="B", entity_type="idea", source_path="b.md"))
    await store.upsert_entity(GraphEntity(name="C", entity_type="event", source_path="c.md"))
    await store.commit()

    assert await store.count_entities_of_type("idea") == 2
    assert await store.count_entities_of_type("event") == 1
    assert await store.count_entities_of_type("nonexistent") == 0
