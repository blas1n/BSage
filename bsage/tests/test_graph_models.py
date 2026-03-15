"""Tests for graph_models dataclasses."""

from bsage.garden.graph_models import GraphEntity, GraphRelationship, ProvenanceRecord


def test_graph_entity_defaults():
    e = GraphEntity(name="BSage", entity_type="project", source_path="garden/idea/bsage.md")
    assert e.name == "BSage"
    assert e.entity_type == "project"
    assert e.source_path == "garden/idea/bsage.md"
    assert e.confidence == 1.0
    assert e.properties == {}
    assert e.id  # auto-generated UUID


def test_graph_entity_custom_fields():
    e = GraphEntity(
        name="Alice",
        entity_type="person",
        source_path="garden/idea/meeting.md",
        id="custom-id",
        properties={"role": "engineer"},
        confidence=0.8,
    )
    assert e.id == "custom-id"
    assert e.properties["role"] == "engineer"
    assert e.confidence == 0.8


def test_graph_entity_unique_ids():
    e1 = GraphEntity(name="A", entity_type="concept", source_path="a.md")
    e2 = GraphEntity(name="B", entity_type="concept", source_path="b.md")
    assert e1.id != e2.id


def test_graph_relationship_defaults():
    r = GraphRelationship(source_id="s1", target_id="t1", rel_type="related_to", source_path="a.md")
    assert r.source_id == "s1"
    assert r.target_id == "t1"
    assert r.rel_type == "related_to"
    assert r.confidence == 1.0
    assert r.id  # auto-generated


def test_provenance_record():
    p = ProvenanceRecord(
        entity_id="e1",
        source_path="garden/idea/x.md",
        extraction_method="rule",
        confidence=1.0,
        extracted_at="2026-03-12T00:00:00Z",
    )
    assert p.extraction_method == "rule"
    assert p.confidence == 1.0
