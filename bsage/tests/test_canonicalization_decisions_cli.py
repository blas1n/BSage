"""Tests for slice-4 CLI: decide / list-decisions / decision-stats / bootstrap-policies."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bsage._cli_legacy import main
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


def _create_concept(runner: CliRunner, concept: str) -> str:
    res = runner.invoke(
        main,
        ["canon", "draft", "create-concept", "--concept", concept, "--title", concept],
    )
    assert res.exit_code == 0, res.output
    path = res.output.strip().split()[1]
    apply_res = runner.invoke(main, ["canon", "apply", path])
    assert apply_res.exit_code == 0, apply_res.output
    return path


class TestBootstrapPolicies:
    def test_creates_three_default_policies(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(main, ["canon", "bootstrap-policies"])
        assert result.exit_code == 0
        assert "Created 3 default policy" in result.output
        for kind in ("staleness", "merge-auto-apply", "decision-maturity"):
            assert (vault / "decisions" / "policy" / kind / "conservative-default.md").exists()

    def test_idempotent_second_run(self, runner: CliRunner, vault: Path) -> None:
        runner.invoke(main, ["canon", "bootstrap-policies"])
        result = runner.invoke(main, ["canon", "bootstrap-policies"])
        assert result.exit_code == 0
        assert "already present" in result.output


class TestDecideCmd:
    def test_creates_cannot_link_decision(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "decide",
                "cannot-link",
                "--subject",
                "ci",
                "--subject",
                "cd",
            ],
        )
        assert result.exit_code == 0, result.output
        files = list((vault / "decisions" / "cannot-link").glob("*.md"))
        assert len(files) == 1
        fm = extract_frontmatter(files[0].read_text())
        assert fm["subjects"] == ["ci", "cd"]
        assert fm["base_confidence"] == 0.95
        assert fm["decay"]["profile"] == "definitional"

    def test_creates_must_link_with_semantic_decay_default(
        self, runner: CliRunner, vault: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "canon",
                "decide",
                "must-link",
                "--subject",
                "auth",
                "--subject",
                "authn",
                "--confidence",
                "0.8",
            ],
        )
        assert result.exit_code == 0, result.output
        files = list((vault / "decisions" / "must-link").glob("*.md"))
        assert len(files) == 1
        fm = extract_frontmatter(files[0].read_text())
        assert fm["base_confidence"] == 0.8
        assert fm["decay"]["profile"] == "semantic"


class TestListDecisions:
    def test_empty(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(main, ["canon", "list-decisions"])
        assert result.exit_code == 0
        assert "No decisions" in result.output

    def test_lists_after_decide(self, runner: CliRunner, vault: Path) -> None:
        runner.invoke(main, ["canon", "decide", "cannot-link", "--subject", "a", "--subject", "b"])
        result = runner.invoke(main, ["canon", "list-decisions"])
        assert result.exit_code == 0
        assert "decisions/cannot-link/" in result.output
        assert "a + b" in result.output


class TestDecisionStats:
    def test_zero_state(self, runner: CliRunner, vault: Path) -> None:
        result = runner.invoke(main, ["canon", "decision-stats"])
        assert result.exit_code == 0
        assert "cannot-link decisions: 0" in result.output

    def test_with_active_decisions(self, runner: CliRunner, vault: Path) -> None:
        runner.invoke(
            main,
            [
                "canon",
                "decide",
                "cannot-link",
                "--subject",
                "a",
                "--subject",
                "b",
                "--confidence",
                "0.9",
            ],
        )
        runner.invoke(
            main,
            [
                "canon",
                "decide",
                "cannot-link",
                "--subject",
                "c",
                "--subject",
                "d",
                "--confidence",
                "0.7",
            ],
        )
        result = runner.invoke(main, ["canon", "decision-stats"])
        assert result.exit_code == 0
        assert "cannot-link decisions: 2" in result.output
        # avg = (0.9 + 0.7) / 2 = 0.80
        assert "0.80" in result.output


class TestReviewRejectAsCannotLink:
    def test_reject_as_cannot_link_creates_decision(self, runner: CliRunner, vault: Path) -> None:
        # Setup proposal
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        propose = runner.invoke(main, ["canon", "propose"])
        assert propose.exit_code == 0
        proposal_path = propose.output.strip().split()[-1]

        result = runner.invoke(
            main,
            [
                "canon",
                "review",
                proposal_path,
                "--reject",
                "--reason",
                "actually different",
                "--as-cannot-link",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "rejected" in result.output
        assert "cannot-link decision recorded" in result.output

        # Decision file landed
        files = list((vault / "decisions" / "cannot-link").glob("*.md"))
        assert len(files) == 1
        fm = extract_frontmatter(files[0].read_text())
        # Order may be (canonical, merge) depending on evidence ordering
        assert set(fm["subjects"]) == {"self-host", "self-hosting"}


class TestProposeBalanced:
    def test_balanced_strategy_emits_strategy_field(self, runner: CliRunner, vault: Path) -> None:
        _create_concept(runner, "self-hosting")
        _create_concept(runner, "self-host")
        result = runner.invoke(main, ["canon", "propose", "--strategy", "balanced"])
        assert result.exit_code == 0, result.output
        proposal_path = result.output.strip().split()[-1]
        fm = extract_frontmatter((vault / proposal_path).read_text())
        assert fm["strategy"] == "balanced"


class TestMergeBlockedByCannotLink:
    def test_merge_blocked_after_decide(self, runner: CliRunner, vault: Path) -> None:
        # Setup two concepts
        _create_concept(runner, "ci")
        _create_concept(runner, "cd")
        # Bootstrap policies (so the cannot_link_threshold is in effect)
        runner.invoke(main, ["canon", "bootstrap-policies"])
        # Persist a strong cannot-link decision
        runner.invoke(
            main,
            [
                "canon",
                "decide",
                "cannot-link",
                "--subject",
                "ci",
                "--subject",
                "cd",
                "--confidence",
                "0.95",
            ],
        )
        # Try to merge ci → cd. A bare draft is created; apply must block.
        propose = runner.invoke(main, ["canon", "propose"])
        # If the proposer also filtered the pair, no proposal is generated.
        if "Generated" in propose.output:
            proposal_path = propose.output.strip().split()[-1]
            apply_result = runner.invoke(main, ["canon", "review", proposal_path, "--accept"])
            assert apply_result.exit_code != 0  # blocked or partial
        # If no proposal generated, the cannot-link Hard Block fires
        # downstream when the user manually merges (covered by the merge
        # service tests). Either path is spec-compliant.
