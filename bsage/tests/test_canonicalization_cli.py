"""Tests for ``bsage canon`` CLI shim (Vertical_Slices §2 demo)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bsage.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def vault(tmp_path: Path):
    """Patch settings so the CLI writes into a tmp vault."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    with patch("bsage.garden.canonicalization.cli.get_settings") as gs:
        gs.return_value.vault_path = vault_root
        yield vault_root


class TestDraftCreateConcept:
    def test_emits_path(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "machine-learning",
                "--title",
                "Machine Learning",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "actions/create-concept/" in result.output
        assert "machine-learning.md" in result.output
        assert "(status: draft)" in result.output

        # Verify file landed
        action_dir = vault / "actions" / "create-concept"
        files = list(action_dir.glob("*.md"))
        assert len(files) == 1
        assert files[0].name.endswith("machine-learning.md")

    def test_invalid_concept_rejected(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "Bad_ID",
                "--title",
                "X",
            ],
        )
        assert result.exit_code != 0
        assert "invalid concept id" in result.output

    def test_with_aliases(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "ml",
                "--title",
                "Machine Learning",
                "--alias",
                "machine_learning",
                "--alias",
                "ML",
            ],
        )
        assert result.exit_code == 0, result.output

        action_dir = vault / "actions" / "create-concept"
        files = list(action_dir.glob("*.md"))
        assert len(files) == 1
        text = files[0].read_text()
        assert "machine_learning" in text
        assert "ML" in text


class TestDraftRetagNotes:
    def test_emits_path(self, runner: CliRunner, vault: Path) -> None:
        garden_dir = vault / "garden" / "seedling"
        garden_dir.mkdir(parents=True)
        (garden_dir / "foo.md").write_text(
            "---\ntags:\n  - ml\n---\n# Foo\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "retag-notes",
                "--path",
                "garden/seedling/foo.md",
                "--add",
                "machine-learning",
                "--remove",
                "ml",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "actions/retag-notes/" in result.output
        assert "foo.md" in result.output

        files = list((vault / "actions" / "retag-notes").glob("*.md"))
        assert len(files) == 1

    def test_path_outside_garden_rejected(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "retag-notes",
                "--path",
                "raw/foo.md",
                "--add",
                "ml",
            ],
        )
        assert result.exit_code != 0
        assert "garden/" in result.output

    def test_no_changes_rejected(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "retag-notes",
                "--path",
                "garden/seedling/foo.md",
            ],
        )
        assert result.exit_code != 0


class TestApply:
    def test_full_create_then_apply(self, runner: CliRunner, vault: Path) -> None:
        # Draft
        draft = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "machine-learning",
                "--title",
                "Machine Learning",
            ],
        )
        assert draft.exit_code == 0
        action_path = draft.output.strip().split()[1]

        # Apply
        result = runner.invoke(main, ["canon", "apply", action_path])
        assert result.exit_code == 0, result.output
        assert "applied" in result.output
        assert "concepts/active/machine-learning.md" in result.output

        # Concept landed in vault
        assert (vault / "concepts" / "active" / "machine-learning.md").exists()

    def test_apply_blocked_returns_nonzero(self, runner: CliRunner, vault: Path) -> None:
        # Apply a draft that targets an already-existing concept
        result = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "ml",
                "--title",
                "ML",
            ],
        )
        path = result.output.strip().split()[1]
        runner.invoke(main, ["canon", "apply", path])

        result2 = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "ml",
                "--title",
                "Duplicate",
            ],
        )
        path2 = result2.output.strip().split()[1]
        applied = runner.invoke(main, ["canon", "apply", path2])
        assert applied.exit_code == 2
        assert "blocked" in applied.output

    def test_full_demo_session(self, runner: CliRunner, vault: Path) -> None:
        """End-to-end Vertical_Slices §2 demo: create concept then retag a note."""
        # 1. Create concept
        d1 = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "create-concept",
                "--concept",
                "machine-learning",
                "--title",
                "Machine Learning",
            ],
        )
        assert d1.exit_code == 0, d1.output
        cp = d1.output.strip().split()[1]
        a1 = runner.invoke(main, ["canon", "apply", cp])
        assert a1.exit_code == 0, a1.output

        # 2. Seed a garden note
        garden_dir = vault / "garden" / "seedling"
        garden_dir.mkdir(parents=True)
        (garden_dir / "foo.md").write_text(
            "---\ntags:\n  - ml\n---\n# Foo\n\nbody.\n",
            encoding="utf-8",
        )

        # 3. Retag
        d2 = runner.invoke(
            main,
            [
                "canon",
                "draft",
                "retag-notes",
                "--path",
                "garden/seedling/foo.md",
                "--add",
                "machine-learning",
                "--remove",
                "ml",
            ],
        )
        assert d2.exit_code == 0, d2.output
        rp = d2.output.strip().split()[1]
        a2 = runner.invoke(main, ["canon", "apply", rp])
        assert a2.exit_code == 0, a2.output

        # 4. Verify final state
        from bsage.garden.markdown_utils import extract_frontmatter

        foo = (vault / "garden" / "seedling" / "foo.md").read_text()
        fm = extract_frontmatter(foo)
        assert fm["tags"] == ["machine-learning"]
