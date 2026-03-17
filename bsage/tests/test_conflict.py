"""Tests for knowledge conflict resolution."""

from bsage.garden.conflict import FactRecord, detect_conflicts, resolve_conflict


def _fact(
    obj: str,
    *,
    context: str = "",
    source_type: str = "inferred",
    captured_at: str = "2026-03-10",
) -> FactRecord:
    return FactRecord(
        note_path="test.md",
        subject="Blasin",
        predicate="prefers",
        object_=obj,
        context=context,
        source_type=source_type,
        captured_at=captured_at,
    )


class TestResolveConflict:
    def test_context_scoping_no_conflict(self):
        a = _fact("Python", context="personal projects")
        b = _fact("C#", context="work")
        result = resolve_conflict(a, b)
        assert result.resolution == "context_scoped"

    def test_source_type_explicit_wins(self):
        a = _fact("Python", source_type="explicit")
        b = _fact("C#", source_type="inferred")
        result = resolve_conflict(a, b)
        assert result.resolution == "source_type"
        assert result.winner.object_ == "Python"

    def test_source_type_inferred_over_observed(self):
        a = _fact("Python", source_type="observed")
        b = _fact("C#", source_type="inferred")
        result = resolve_conflict(a, b)
        assert result.resolution == "source_type"
        assert result.winner.object_ == "C#"

    def test_recency_newer_wins(self):
        a = _fact("Python", captured_at="2026-01-01")
        b = _fact("C#", captured_at="2026-03-15")
        result = resolve_conflict(a, b)
        assert result.resolution == "recency"
        assert result.winner.object_ == "C#"

    def test_unresolved_same_everything(self):
        a = _fact("Python")
        b = _fact("C#")
        result = resolve_conflict(a, b)
        assert result.resolution == "unresolved"

    def test_context_empty_does_not_scope(self):
        a = _fact("Python", context="")
        b = _fact("C#", context="work")
        result = resolve_conflict(a, b)
        # Empty context means we can't scope — falls through to source_type/recency
        assert result.resolution != "context_scoped"


class TestDetectConflicts:
    def test_finds_conflicts(self):
        facts = [
            _fact("Python"),
            _fact("C#"),
            _fact("Rust", captured_at="2026-03-12"),
        ]
        conflicts = detect_conflicts(facts)
        assert len(conflicts) == 3  # Python-C#, Python-Rust, C#-Rust

    def test_no_conflict_same_object(self):
        facts = [_fact("Python"), _fact("Python")]
        conflicts = detect_conflicts(facts)
        assert conflicts == []

    def test_no_conflict_single_fact(self):
        facts = [_fact("Python")]
        conflicts = detect_conflicts(facts)
        assert conflicts == []

    def test_different_predicates_no_conflict(self):
        a = FactRecord("a.md", "Blasin", "prefers", "Python")
        b = FactRecord("b.md", "Blasin", "uses", "C#")
        conflicts = detect_conflicts([a, b])
        assert conflicts == []
