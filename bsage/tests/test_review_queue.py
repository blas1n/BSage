"""Tests for review_queue generation."""

from __future__ import annotations

import pytest

from bsage.garden.graph_models import ConfidenceLevel, GraphEntity, GraphRelationship
from bsage.garden.review_queue import generate_review_queue
from bsage.garden.storage import FileSystemStorage
from bsage.garden.vault_backend import VaultBackend


@pytest.fixture
async def setup(tmp_path):
    storage = FileSystemStorage(tmp_path / "vault")
    backend = VaultBackend(storage)
    await backend.initialize()
    yield backend, storage
    await backend.close()


async def test_review_queue_empty(setup):
    backend, storage = setup
    count = await generate_review_queue(backend, storage)
    assert count == 0
    content = await storage.read(".bsage/review_queue.md")
    assert "No items pending review" in content


async def test_review_queue_with_ambiguous_relationship(setup):
    backend, storage = setup

    e1 = GraphEntity(name="Alice", entity_type="person", source_path="people/alice.md")
    e2 = GraphEntity(
        name="Bob",
        entity_type="person",
        source_path="people/bob.md",
        confidence=ConfidenceLevel.AMBIGUOUS,
    )
    id1 = await backend.upsert_entity(e1)
    id2 = await backend.upsert_entity(e2)
    await backend.upsert_relationship(
        GraphRelationship(
            source_id=id1,
            target_id=id2,
            rel_type="works_with",
            source_path="people/alice.md",
            confidence=ConfidenceLevel.AMBIGUOUS,
        )
    )

    count = await generate_review_queue(backend, storage)
    assert count >= 1  # At least the edge

    content = await storage.read(".bsage/review_queue.md")
    assert "Alice" in content
    assert "Bob" in content
    assert "works_with" in content
    assert "No items pending review" not in content


async def test_review_queue_skips_confirmed(setup):
    backend, storage = setup

    e1 = GraphEntity(name="Alice", entity_type="person", source_path="a.md")
    e2 = GraphEntity(name="Bob", entity_type="person", source_path="b.md")
    id1 = await backend.upsert_entity(e1)
    id2 = await backend.upsert_entity(e2)
    await backend.upsert_relationship(
        GraphRelationship(
            source_id=id1,
            target_id=id2,
            rel_type="works_with",
            source_path="a.md",
            confidence=ConfidenceLevel.EXTRACTED,
        )
    )

    count = await generate_review_queue(backend, storage)
    assert count == 0
