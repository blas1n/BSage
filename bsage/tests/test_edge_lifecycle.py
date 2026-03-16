"""Tests for edge lifecycle — promotion and demotion."""

import pytest

from bsage.garden.edge_lifecycle import EdgeLifecycleConfig, EdgeLifecycleEvaluator
from bsage.garden.graph_models import GraphEntity, GraphRelationship
from bsage.garden.graph_store import GraphStore


@pytest.fixture()
async def store(tmp_path):
    s = GraphStore(tmp_path / "graph.db")
    await s.initialize()
    yield s
    await s.close()


async def _insert_weak_edge(store, src_name, tgt_name, source_path):
    """Helper: insert a note entity + target entity + a weak edge.

    Each source_path creates a distinct note entity (entity_type='idea')
    so relationships from different notes are not deduped.
    """
    # Note entity — unique per source_path since name differs
    note_name = f"{src_name} ({source_path})"
    src = GraphEntity(name=note_name, entity_type="idea", source_path=source_path)
    tgt = GraphEntity(name=tgt_name, entity_type="concept", source_path=source_path)
    src_id = await store.upsert_entity(src)
    tgt_id = await store.upsert_entity(tgt)
    rel = GraphRelationship(
        source_id=src_id,
        target_id=tgt_id,
        rel_type="references",
        source_path=source_path,
        weight=0.1,
        edge_type="weak",
    )
    await store.upsert_relationship(rel)
    await store.commit()


@pytest.mark.asyncio()
async def test_find_promotion_candidates(store):
    config = EdgeLifecycleConfig(promotion_min_mentions=2)
    evaluator = EdgeLifecycleEvaluator(store, config)

    # Same pair mentioned from 3 different notes
    await _insert_weak_edge(store, "Alice", "Docker", "note1.md")
    await _insert_weak_edge(store, "Alice", "Docker", "note2.md")
    await _insert_weak_edge(store, "Alice", "Docker", "note3.md")

    # Different pair mentioned once only
    await _insert_weak_edge(store, "Bob", "Python", "note1.md")

    candidates = await evaluator.find_promotion_candidates()
    assert len(candidates) == 1
    assert candidates[0]["target_name"] == "Docker"
    assert candidates[0]["mention_count"] >= 2


@pytest.mark.asyncio()
async def test_find_promotion_candidates_empty(store):
    config = EdgeLifecycleConfig(promotion_min_mentions=5)
    evaluator = EdgeLifecycleEvaluator(store, config)
    await _insert_weak_edge(store, "Alice", "Docker", "note1.md")
    candidates = await evaluator.find_promotion_candidates()
    assert candidates == []


@pytest.mark.asyncio()
async def test_promote_edges(store):
    config = EdgeLifecycleConfig(promotion_min_mentions=2, promoted_weight=0.8)
    evaluator = EdgeLifecycleEvaluator(store, config)

    await _insert_weak_edge(store, "Alice", "Docker", "note1.md")
    await _insert_weak_edge(store, "Alice", "Docker", "note2.md")

    promoted = await evaluator.promote_edges()
    assert promoted >= 1

    # Verify edges pointing to Docker are now strong
    entity = await store.get_entity_by_name("Docker")
    assert entity is not None
    neighbors = await store.query_neighbors(entity.id)
    assert any(r.edge_type == "strong" for r, _ in neighbors)


@pytest.mark.asyncio()
async def test_find_demotion_candidates(store):
    config = EdgeLifecycleConfig(demotion_days=0)  # anything qualifies
    evaluator = EdgeLifecycleEvaluator(store, config)

    src = GraphEntity(name="Alice", entity_type="person", source_path="a.md")
    tgt = GraphEntity(name="Docker", entity_type="tool", source_path="a.md")
    src_id = await store.upsert_entity(src)
    tgt_id = await store.upsert_entity(tgt)
    rel = GraphRelationship(
        source_id=src_id,
        target_id=tgt_id,
        rel_type="uses",
        source_path="a.md",
        weight=1.0,
        edge_type="strong",
    )
    await store.upsert_relationship(rel)
    await store.commit()

    candidates = await evaluator.find_demotion_candidates()
    assert len(candidates) == 1
    assert candidates[0]["source_name"] == "Alice"


@pytest.mark.asyncio()
async def test_demote_edges(store):
    config = EdgeLifecycleConfig(demotion_days=0, weak_weight=0.1)
    evaluator = EdgeLifecycleEvaluator(store, config)

    src = GraphEntity(name="Alice", entity_type="person", source_path="a.md")
    tgt = GraphEntity(name="Docker", entity_type="tool", source_path="a.md")
    src_id = await store.upsert_entity(src)
    tgt_id = await store.upsert_entity(tgt)
    rel = GraphRelationship(
        source_id=src_id,
        target_id=tgt_id,
        rel_type="uses",
        source_path="a.md",
        weight=1.0,
        edge_type="strong",
    )
    await store.upsert_relationship(rel)
    await store.commit()

    demoted = await evaluator.demote_edges()
    assert demoted == 1

    # Verify edge is now weak
    neighbors = await store.query_neighbors(src_id)
    docker_rels = [r for r, e in neighbors if e.name == "Docker"]
    assert docker_rels[0].edge_type == "weak"
    assert docker_rels[0].weight == 0.1
