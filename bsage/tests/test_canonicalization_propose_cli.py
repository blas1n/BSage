"""Tests for slice-3 CLI: bsage canon propose / list-proposals / review."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bsage.cli import main
from bsage.garden.markdown_utils import extract_frontmatter


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def vault(tmp_path: Path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    with patch("bsage.garden.canonicalization.cli.get_settings") as gs:
        gs.return_value.vault_path = vault_root
        yield vault_root


def _create_concept(runner: CliRunner, concept: str, title: str | None = None) -> str:
    res = runner.invoke(
        main,
        [
            "canon",
            "draft",
            "create-concept",
            "--concept",
            concept,
            "--title",
            title or concept,
        ],
    )
    assert res.exit_code == 0, res.output
    path = res.output.strip().split()[1]
    apply_res = runner.invoke(main, ["canon", "apply", path])
    assert apply_res.exit_code == 0, apply_res.output
    return path


class TestProposeCmd:
    def test_empty_vault_no_proposals(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(main, ["canon", "propose"])
        assert result.exit_code == 0
        assert "No new proposals" in result.output

    def test_close_pair_generates_proposal(self, runner: CliRunner, vault: Path) -> None:
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")

        result = runner.invoke(main, ["canon", "propose"])
        assert result.exit_code == 0, result.output
        assert "Generated 1 proposal" in result.output
        assert "proposals/merge-concepts/" in result.output

        files = list((vault / "proposals" / "merge-concepts").glob("*.md"))
        assert len(files) == 1


class TestListProposalsCmd:
    def test_lists_pending(self, runner: CliRunner, vault: Path) -> None:
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        runner.invoke(main, ["canon", "propose"])

        result = runner.invoke(main, ["canon", "list-proposals"])
        assert result.exit_code == 0
        assert "proposals/merge-concepts/" in result.output

    def test_empty_status(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(main, ["canon", "list-proposals"])
        assert result.exit_code == 0
        assert "No proposals" in result.output


class TestReviewCmd:
    def test_review_read_only(self, runner: CliRunner, vault: Path) -> None:
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        propose = runner.invoke(main, ["canon", "propose"])
        proposal_path = propose.output.strip().split()[-1]

        result = runner.invoke(main, ["canon", "review", proposal_path])
        assert result.exit_code == 0, result.output
        assert "=== Proposal: merge-concepts" in result.output
        assert "Evidence:" in result.output
        assert "alias_exact" in result.output
        assert "Linked action drafts:" in result.output

    def test_review_accept_applies_merge(self, runner: CliRunner, vault: Path) -> None:
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        propose = runner.invoke(main, ["canon", "propose"])
        proposal_path = propose.output.strip().split()[-1]

        # Garden note referencing the old id
        garden_dir = vault / "garden" / "seedling"
        garden_dir.mkdir(parents=True)
        (garden_dir / "foo.md").write_text(
            "---\ntags:\n  - self-host\n---\n# Foo\n",
            encoding="utf-8",
        )

        result = runner.invoke(main, ["canon", "review", proposal_path, "--accept"])
        assert result.exit_code == 0, result.output
        assert "accepted" in result.output

        # Tombstone created
        assert (vault / "concepts" / "merged" / "self-host.md").exists()
        # Old active removed
        assert not (vault / "concepts" / "active" / "self-host.md").exists()
        # Garden retagged
        fm = extract_frontmatter((garden_dir / "foo.md").read_text())
        assert fm["tags"] == ["self-hosting"]

        # Proposal status updated
        prop_raw = (vault / proposal_path).read_text()
        prop_fm = extract_frontmatter(prop_raw)
        assert prop_fm["status"] == "accepted"
        assert len(prop_fm["result_actions"]) == 1

    def test_review_reject_marks_rejected(self, runner: CliRunner, vault: Path) -> None:
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        propose = runner.invoke(main, ["canon", "propose"])
        proposal_path = propose.output.strip().split()[-1]

        result = runner.invoke(
            main,
            ["canon", "review", proposal_path, "--reject", "--reason", "not now"],
        )
        assert result.exit_code == 0, result.output
        assert "rejected" in result.output

        prop_fm = extract_frontmatter((vault / proposal_path).read_text())
        assert prop_fm["status"] == "rejected"
        # Original aliases still present, no merge happened
        assert (vault / "concepts" / "active" / "self-host.md").exists()
        assert not (vault / "concepts" / "merged" / "self-host.md").exists()

    def test_review_missing_proposal_errors(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(main, ["canon", "review", "proposals/merge-concepts/missing.md"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestProposeReviewE2E:
    def test_full_demo_session(self, runner: CliRunner, vault: Path) -> None:
        """Vertical_Slices §4 demo: propose → review → accept → vault changes."""
        # Setup: two near-duplicate active concepts. Garden frequency must
        # favor `self-hosting` so the proposer picks it as canonical
        # (highest usage wins; ties broken by length).
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        garden_dir = vault / "garden" / "seedling"
        garden_dir.mkdir(parents=True)
        for i in range(3):
            (garden_dir / f"hosting{i}.md").write_text(
                "---\ntags:\n  - self-hosting\n---\n# hosting\n",
                encoding="utf-8",
            )
        (garden_dir / "a.md").write_text("---\ntags:\n  - self-host\n---\n# A\n", encoding="utf-8")

        # 1. Propose
        propose = runner.invoke(main, ["canon", "propose"])
        assert propose.exit_code == 0, propose.output
        proposal_path = propose.output.strip().split()[-1]

        # 2. List
        listing = runner.invoke(main, ["canon", "list-proposals"])
        assert proposal_path in listing.output

        # 3. Review (read-only)
        review = runner.invoke(main, ["canon", "review", proposal_path])
        assert review.exit_code == 0

        # 4. Accept
        accept = runner.invoke(main, ["canon", "review", proposal_path, "--accept"])
        assert accept.exit_code == 0

        # 5. Verify final vault state
        fm = extract_frontmatter((garden_dir / "a.md").read_text())
        assert fm["tags"] == ["self-hosting"]
        assert (vault / "concepts" / "merged" / "self-host.md").exists()

        # 6. Re-running propose finds nothing (concept is now merged)
        again = runner.invoke(main, ["canon", "propose"])
        assert "No new proposals" in again.output
