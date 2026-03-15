"""Tests for GraphExtractor — rule-based entity/relationship extraction."""

from bsage.garden.graph_extractor import GraphExtractor


def _make_note(
    *,
    note_type: str = "idea",
    title: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    related: list[str] | None = None,
    body: str = "",
) -> str:
    """Build a minimal markdown note with frontmatter."""
    fm_lines = ["---"]
    fm_lines.append(f"type: {note_type}")
    if title:
        fm_lines.append(f"title: {title}")
    if tags:
        fm_lines.append(f"tags: [{', '.join(tags)}]")
    if source:
        fm_lines.append(f"source: {source}")
    if related:
        items = ", ".join(f"'[[{r}]]'" for r in related)
        fm_lines.append(f"related: [{items}]")
    fm_lines.append("---")
    fm_lines.append(body)
    return "\n".join(fm_lines)


def test_extract_note_entity():
    content = _make_note(title="BSage Project")
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("garden/idea/bsage.md", content)

    note_entities = [e for e in entities if e.entity_type == "note"]
    assert len(note_entities) == 1
    assert note_entities[0].name == "BSage Project"
    assert note_entities[0].source_path == "garden/idea/bsage.md"
    assert note_entities[0].confidence == 1.0


def test_extract_note_entity_from_filename():
    """When no title in frontmatter, derive from filename."""
    content = _make_note()
    extractor = GraphExtractor()
    entities, _ = extractor.extract_from_note("garden/idea/my-cool-idea.md", content)

    note_entities = [e for e in entities if e.entity_type == "note"]
    assert note_entities[0].name == "my cool idea"


def test_extract_project_type():
    content = _make_note(note_type="project", title="BSage")
    extractor = GraphExtractor()
    entities, _ = extractor.extract_from_note("garden/idea/bsage.md", content)
    assert entities[0].entity_type == "project"


def test_extract_tags():
    content = _make_note(tags=["ai", "productivity"])
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("a.md", content)

    tag_entities = [e for e in entities if e.entity_type == "tag"]
    assert len(tag_entities) == 2
    tag_names = {e.name for e in tag_entities}
    assert tag_names == {"ai", "productivity"}

    tagged_rels = [r for r in relationships if r.rel_type == "tagged_with"]
    assert len(tagged_rels) == 2


def test_extract_source():
    content = _make_note(source="telegram-input")
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("a.md", content)

    source_entities = [e for e in entities if e.entity_type == "source"]
    assert len(source_entities) == 1
    assert source_entities[0].name == "telegram-input"

    created_rels = [r for r in relationships if r.rel_type == "created_by"]
    assert len(created_rels) == 1


def test_extract_related_wikilinks():
    content = _make_note(related=["BSage", "Graph RAG"])
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("a.md", content)

    related_entities = [
        e for e in entities if e.entity_type == "note" and e.name in ("BSage", "Graph RAG")
    ]
    assert len(related_entities) == 2

    related_rels = [r for r in relationships if r.rel_type == "related_to"]
    assert len(related_rels) == 2


def test_extract_body_wikilinks():
    body = "This connects to [[Python]] and [[FastAPI]] for the backend."
    content = _make_note(body=body)
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("a.md", content)

    ref_rels = [r for r in relationships if r.rel_type == "references"]
    assert len(ref_rels) == 2
    ref_names = {e.name for e in entities if any(r.target_id == e.id for r in ref_rels)}
    assert ref_names == {"Python", "FastAPI"}


def test_body_wikilinks_dedup_with_related():
    """Body wikilinks that already appear in related are not duplicated."""
    body = "Also see [[BSage]] for more details."
    content = _make_note(related=["BSage"], body=body)
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("a.md", content)

    bsage_rels = [
        r
        for r in relationships
        if any(e.name == "BSage" and e.id in (r.source_id, r.target_id) for e in entities)
    ]
    # Should have related_to but NOT references (deduped)
    rel_types = {r.rel_type for r in bsage_rels}
    assert "related_to" in rel_types
    assert "references" not in rel_types


def test_body_wikilinks_dedup_within_body():
    """Same wikilink appearing multiple times in body produces only one reference."""
    body = "See [[Python]] and then [[Python]] again."
    content = _make_note(body=body)
    extractor = GraphExtractor()
    _, relationships = extractor.extract_from_note("a.md", content)

    ref_rels = [r for r in relationships if r.rel_type == "references"]
    assert len(ref_rels) == 1


def test_extract_no_frontmatter():
    """Gracefully handles notes without frontmatter."""
    content = "# Just a heading\n\nSome text with [[a link]]."
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("notes/plain.md", content)

    assert len(entities) >= 1  # note entity + link entity
    note_entities = [e for e in entities if e.source_path == "notes/plain.md"]
    assert len(note_entities) >= 1


def test_extract_empty_note():
    content = "---\ntype: idea\n---\n"
    extractor = GraphExtractor()
    entities, relationships = extractor.extract_from_note("a.md", content)

    # Just the note entity, no tags/source/related
    assert len(entities) == 1
    assert len(relationships) == 0


def test_extract_properties_from_frontmatter():
    content = "---\ntype: idea\nstatus: growing\ncaptured_at: 2026-03-12\n---\n"
    extractor = GraphExtractor()
    entities, _ = extractor.extract_from_note("a.md", content)

    props = entities[0].properties
    assert props["type"] == "idea"
    assert props["status"] == "growing"
    assert str(props["captured_at"]) == "2026-03-12"
