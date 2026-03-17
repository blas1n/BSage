"""Tests for OntologyRegistry (v2.2 schema)."""

import pytest
import yaml

from bsage.garden.ontology import OntologyRegistry


@pytest.mark.asyncio()
async def test_load_creates_default(tmp_path):
    path = tmp_path / ".bsage" / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert path.exists()
    assert registry.schema_version == 3
    assert registry.is_valid_entity_type("person")
    assert registry.is_valid_entity_type("idea")
    assert registry.is_valid_entity_type("event")
    assert registry.is_valid_entity_type("fact")
    assert registry.is_valid_entity_type("preference")
    assert registry.is_valid_relationship_type("related_to")
    assert registry.is_valid_relationship_type("references")
    assert registry.is_valid_relationship_type("attendees")
    assert registry.is_valid_relationship_type("supersedes")


@pytest.mark.asyncio()
async def test_load_existing_file(tmp_path):
    path = tmp_path / "ontology.yaml"
    data = {
        "schema_version": 99,
        "entity_types": {"custom": {"description": "A custom type", "knowledge_layer": "semantic"}},
        "relation_types": {"custom_rel": {"description": "A custom rel", "default_weight": 0.5}},
    }
    with open(path, "w") as f:
        yaml.dump(data, f)

    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.schema_version == 99
    assert registry.is_valid_entity_type("custom")
    assert not registry.is_valid_entity_type("person")


@pytest.mark.asyncio()
async def test_get_entity_types_excludes_deprecated(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    types = registry.get_entity_types()
    assert "person" in types
    assert "knowledge_layer" in types["person"]


@pytest.mark.asyncio()
async def test_get_relation_types(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    types = registry.get_relation_types()
    assert "related_to" in types
    assert "default_weight" in types["related_to"]
    assert "inverse" in types["related_to"]


@pytest.mark.asyncio()
async def test_entity_types_have_v22_fields(tmp_path):
    path = tmp_path / ".bsage" / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    # Entity types with folders
    for etype in ("idea", "insight", "person", "project", "event", "task", "fact", "preference"):
        assert registry.is_valid_entity_type(etype), f"Missing entity type: {etype}"
        assert registry.get_entity_folder(etype) is not None, f"Missing folder for: {etype}"
        assert registry.get_knowledge_layer(etype) in (
            "semantic",
            "episodic",
            "procedural",
            "affective",
        ), f"Invalid knowledge_layer for: {etype}"

    # Entity types without folders (virtual types)
    for etype in ("tag", "source"):
        assert registry.is_valid_entity_type(etype)
        assert registry.get_entity_folder(etype) is None

    # Relationship types
    for rtype in (
        "related_to",
        "references",
        "tagged_with",
        "belongs_to",
        "attends",
        "attendees",
        "supersedes",
        "prefers",
    ):
        assert registry.is_valid_relationship_type(rtype), f"Missing rel type: {rtype}"


@pytest.mark.asyncio()
async def test_relation_types_have_v22_fields(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    types = registry.get_relation_types()
    attendees = types["attendees"]
    assert attendees["domain"] == "event"
    assert attendees["range"] == "person"
    assert attendees["inverse"] == "attends"
    assert attendees["default_weight"] == 1.0

    supersedes = types["supersedes"]
    assert supersedes["domain"] == "fact"
    assert supersedes["range"] == "fact"


@pytest.mark.asyncio()
async def test_add_entity_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_entity_type(
        "exercise",
        "운동 기록",
        folder="exercises/",
        knowledge_layer="episodic",
    )
    assert added is True
    assert registry.is_valid_entity_type("exercise")
    assert registry.get_entity_folder("exercise") == "exercises/"
    assert registry.get_knowledge_layer("exercise") == "episodic"

    # Verify persisted
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "exercise" in data["entity_types"]


@pytest.mark.asyncio()
async def test_add_entity_type_duplicate(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_entity_type("person", "Duplicate")
    assert added is False


@pytest.mark.asyncio()
async def test_add_relationship_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    added = await registry.add_relationship_type(
        "mentors",
        "멘토 관계",
        domain="person",
        range_="person",
        inverse="mentored_by",
        default_weight=0.8,
    )
    assert added is True
    assert registry.is_valid_relationship_type("mentors")
    assert registry.get_relation_weight("mentors") == 0.8
    assert registry.get_inverse("mentors") == "mentored_by"


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


@pytest.mark.asyncio()
async def test_get_relation_weight(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.get_relation_weight("attendees") == 1.0
    assert registry.get_relation_weight("references") == 0.3
    assert registry.get_relation_weight("nonexistent") == 0.5  # default


@pytest.mark.asyncio()
async def test_get_inverse(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.get_inverse("attendees") == "attends"
    assert registry.get_inverse("supersedes") == "superseded_by"
    assert registry.get_inverse("nonexistent") is None


@pytest.mark.asyncio()
async def test_evolution_config(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    config = registry.get_evolution_config()
    assert config["create_threshold"] == 5
    assert config["merge_jaccard_threshold"] == 0.7
    assert config["deprecate_days"] == 90
    assert config["edge_promotion_min_mentions"] == 3


@pytest.mark.asyncio()
async def test_deprecated_entity_type_excluded(tmp_path):
    path = tmp_path / "ontology.yaml"
    data = {
        "schema_version": 3,
        "entity_types": {
            "active": {"description": "Active", "knowledge_layer": "semantic"},
            "old": {"description": "Old", "knowledge_layer": "semantic", "deprecated": True},
        },
        "relation_types": {},
    }
    with open(path, "w") as f:
        yaml.dump(data, f)

    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.is_valid_entity_type("active")
    assert not registry.is_valid_entity_type("old")

    all_types = registry.get_all_entity_types()
    assert "old" in all_types

    active_types = registry.get_entity_types()
    assert "old" not in active_types


@pytest.mark.asyncio()
async def test_version_property_compat(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    assert registry.version == "3"
    assert registry.schema_version == 3


# ------------------------------------------------------------------
# Schema evolution operations (v2.2)
# ------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_deprecate_entity_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    result = await registry.deprecate_entity_type("tool", reason="unused")
    assert result is True
    assert not registry.is_valid_entity_type("tool")
    # Still in get_all
    assert "tool" in registry.get_all_entity_types()
    # Changelog created
    changelog = (tmp_path / "ontology-changelog.md").read_text()
    assert "DEPRECATE" in changelog
    assert "tool" in changelog


@pytest.mark.asyncio()
async def test_deprecate_already_deprecated(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    await registry.deprecate_entity_type("tool")
    result = await registry.deprecate_entity_type("tool")
    assert result is False


@pytest.mark.asyncio()
async def test_merge_entity_types(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    # Add two types then merge
    await registry.add_entity_type("work_tool", "Work tool", folder="work_tools/")
    await registry.add_entity_type("dev_tool", "Dev tool", folder="dev_tools/")
    result = await registry.merge_entity_types("dev_tool", "work_tool", reason="82% overlap")
    assert result is True
    assert not registry.is_valid_entity_type("dev_tool")
    assert registry.is_valid_entity_type("work_tool")

    all_types = registry.get_all_entity_types()
    assert all_types["dev_tool"]["merged_into"] == "work_tool"

    changelog = (tmp_path / "ontology-changelog.md").read_text()
    assert "MERGE" in changelog


@pytest.mark.asyncio()
async def test_merge_nonexistent_fails(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    result = await registry.merge_entity_types("nonexistent", "person")
    assert result is False


@pytest.mark.asyncio()
async def test_split_entity_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    result = await registry.split_entity_type(
        "concept",
        "technology",
        "기술 스택",
        folder="technologies/",
        knowledge_layer="semantic",
        reason="bimodal distribution",
    )
    assert result is True
    assert registry.is_valid_entity_type("technology")
    assert registry.get_entity_folder("technology") == "technologies/"

    all_types = registry.get_all_entity_types()
    assert all_types["technology"]["split_from"] == "concept"

    changelog = (tmp_path / "ontology-changelog.md").read_text()
    assert "SPLIT" in changelog


@pytest.mark.asyncio()
async def test_split_duplicate_name_fails(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    result = await registry.split_entity_type("concept", "person", "Duplicate")
    assert result is False


@pytest.mark.asyncio()
async def test_promote_entity_type(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    result = await registry.promote_entity_type("concept", reason="high usage")
    assert result is True

    changelog = (tmp_path / "ontology-changelog.md").read_text()
    assert "PROMOTE" in changelog


@pytest.mark.asyncio()
async def test_promote_nonexistent_fails(tmp_path):
    path = tmp_path / "ontology.yaml"
    registry = OntologyRegistry(path)
    await registry.load()

    result = await registry.promote_entity_type("nonexistent")
    assert result is False
