"""Tests for OntologyRegistry."""

import pytest
import yaml

from bsage.garden.ontology import OntologyRegistry


@pytest.mark.asyncio()
async def test_load_creates_default(tmp_path):
    path = tmp_path / ".bsage" / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert path.exists()
    assert registry.is_valid_entity_type("note")
    assert registry.is_valid_entity_type("person")
    assert registry.is_valid_entity_type("project")
    assert registry.is_valid_relationship_type("related_to")
    assert registry.is_valid_relationship_type("references")


@pytest.mark.asyncio()
async def test_load_existing_file(tmp_path):
    path = tmp_path / "ontology.yaml"
    data = {
        "version": "2.0",
        "entity_types": {"custom": {"description": "A custom type"}},
        "relationship_types": {"custom_rel": {"description": "A custom rel"}},
    }
    with open(path, "w") as f:
        yaml.dump(data, f)

    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.version == "2.0"
    assert registry.is_valid_entity_type("custom")
    assert not registry.is_valid_entity_type("note")  # not in custom file


@pytest.mark.asyncio()
async def test_get_entity_types(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    types = registry.get_entity_types()
    assert "note" in types
    assert "description" in types["note"]


@pytest.mark.asyncio()
async def test_get_relationship_types(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    types = registry.get_relationship_types()
    assert "related_to" in types


@pytest.mark.asyncio()
async def test_default_ontology_has_expanded_types(tmp_path):
    path = tmp_path / ".bsage" / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    # Entity types
    for etype in ("note", "person", "concept", "project", "event", "task", "organization", "tool"):
        assert registry.is_valid_entity_type(etype), f"Missing entity type: {etype}"

    # Relationship types
    for rtype in (
        "related_to",
        "references",
        "tagged_with",
        "depends_on",
        "assigned_to",
        "belongs_to",
    ):
        assert registry.is_valid_relationship_type(rtype), f"Missing rel type: {rtype}"


@pytest.mark.asyncio()
async def test_add_entity_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_entity_type("custom_type", "A custom type")
    assert added is True
    assert registry.is_valid_entity_type("custom_type")

    # Verify persisted
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "custom_type" in data["entity_types"]


@pytest.mark.asyncio()
async def test_add_entity_type_duplicate(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_entity_type("note", "Duplicate")
    assert added is False  # already exists


@pytest.mark.asyncio()
async def test_add_relationship_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_relationship_type("custom_rel", "A custom relationship")
    assert added is True
    assert registry.is_valid_relationship_type("custom_rel")


@pytest.mark.asyncio()
async def test_add_relationship_type_duplicate(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_relationship_type("related_to", "Dup")
    assert added is False


@pytest.mark.asyncio()
async def test_validate_entity_type_fallback(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.validate_entity_type("person") == "person"
    assert registry.validate_entity_type("unknown_type") == "concept"


@pytest.mark.asyncio()
async def test_validate_relationship_type_fallback(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.validate_relationship_type("uses") == "uses"
    assert registry.validate_relationship_type("unknown_rel") == "related_to"
