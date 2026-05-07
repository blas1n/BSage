"""``bsage canon`` — CLI shim across slices 1-4."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import structlog

from bsage.core.config import get_settings
from bsage.garden.canonicalization import paths as canon_paths
from bsage.garden.canonicalization.decisions import DecisionMemory
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.policies import PolicyResolver
from bsage.garden.canonicalization.proposals import (
    BalancedProposer,
    DeterministicProposer,
)
from bsage.garden.canonicalization.resolver import TagResolver
from bsage.garden.canonicalization.service import CanonicalizationService
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage

logger = structlog.get_logger(__name__)


async def _build_service_async(
    vault_path: Path,
) -> tuple[CanonicalizationService, FileSystemStorage]:
    vault_path.mkdir(parents=True, exist_ok=True)
    storage = FileSystemStorage(vault_path)
    index = InMemoryCanonicalizationIndex()
    await index.initialize(storage)
    store = NoteStore(storage)
    decisions = DecisionMemory(index=index, store=store)
    policy_resolver = PolicyResolver(index=index, store=store)
    service = CanonicalizationService(
        store=store,
        lock=AsyncIOMutationLock(),
        index=index,
        resolver=TagResolver(index=index),
        decisions=decisions,
        policies=policy_resolver,
    )
    return service, storage


def _resolve_vault(vault_path: Path | None) -> Path:
    if vault_path is not None:
        return vault_path
    settings = get_settings()
    return Path(settings.vault_path).expanduser().resolve()


def _run_with_service(coro_factory):  # noqa: ANN001 — generic callable
    """Run an async function that takes (service, storage) → result.

    The service is built per-invocation so the in-memory index reflects
    on-disk state at the time of the call.
    """

    async def _runner():
        vault_path = _resolve_vault(None)
        service, storage = await _build_service_async(vault_path)
        return await coro_factory(service, storage)

    return asyncio.run(_runner())


@click.group("canon")
def canon_group() -> None:
    """Canonicalization commands (concepts, tags, actions)."""


@canon_group.group("draft")
def draft_group() -> None:
    """Create a typed action draft (no apply)."""


@draft_group.command("create-concept")
@click.option("--concept", required=True, help="Concept id (e.g. machine-learning).")
@click.option("--title", required=True, help="Display title (used as H1).")
@click.option(
    "--alias",
    "aliases",
    multiple=True,
    help="Alias to register. Repeatable.",
)
def draft_create_concept(concept: str, title: str, aliases: tuple[str, ...]) -> None:
    """Draft a CreateConcept action."""
    if not canon_paths.is_valid_concept_id(concept):
        raise click.BadParameter(f"invalid concept id {concept!r}. Use lowercase + hyphens.")
    params: dict[str, Any] = {"concept": concept, "title": title}
    if aliases:
        params["aliases"] = list(aliases)

    async def _go(service, _storage):
        return await service.create_action_draft(kind="create-concept", params=params)

    path = _run_with_service(_go)
    click.echo(f"created {path} (status: draft)")


@draft_group.command("retag-notes")
@click.option(
    "--path",
    "garden_path",
    required=True,
    help="Vault-relative garden note path (must start with garden/).",
)
@click.option(
    "--add",
    "add_tags",
    multiple=True,
    help="Concept id to add. Repeatable.",
)
@click.option(
    "--remove",
    "remove_tags",
    multiple=True,
    help="Concept id to remove. Repeatable.",
)
@click.option("--slug", default=None, help="Filename slug (defaults to last path component).")
def draft_retag_notes(
    garden_path: str,
    add_tags: tuple[str, ...],
    remove_tags: tuple[str, ...],
    slug: str | None,
) -> None:
    """Draft a RetagNotes action for a single garden file."""
    if not garden_path.startswith("garden/"):
        raise click.BadParameter(f"path must start with garden/: {garden_path!r}")
    if not add_tags and not remove_tags:
        raise click.BadParameter("at least one --add or --remove is required")

    derived_slug = slug or _slug_from_path(garden_path)
    if not canon_paths.is_valid_concept_id(derived_slug):
        raise click.BadParameter(
            f"derived slug {derived_slug!r} is not a valid id; pass --slug explicitly"
        )

    params: dict[str, Any] = {
        "changes": [
            {
                "path": garden_path,
                "remove_tags": list(remove_tags),
                "add_tags": list(add_tags),
            }
        ]
    }

    async def _go(service, _storage):
        return await service.create_action_draft(
            kind="retag-notes", params=params, slug=derived_slug
        )

    path = _run_with_service(_go)
    click.echo(f"created {path} (status: draft)")


def _slug_from_path(garden_path: str) -> str:
    stem = garden_path.rsplit("/", 1)[-1]
    if stem.endswith(".md"):
        stem = stem[: -len(".md")]
    return stem


@canon_group.command("apply")
@click.argument("action_path")
def apply_cmd(action_path: str) -> None:
    """Apply a typed action by vault-relative path."""

    async def _go(service, _storage):
        return await service.apply_action(action_path, actor="cli")

    result = _run_with_service(_go)

    if result.final_status == "applied":
        click.echo("applied. affected:")
        for p in result.affected_paths:
            click.echo(f"  {p}")
        return
    if result.final_status == "blocked":
        click.echo(f"blocked. see validation.hard_blocks in {action_path}", err=True)
        raise SystemExit(2)
    if result.final_status == "failed":
        click.echo(f"failed: {result.error}", err=True)
        raise SystemExit(3)
    click.echo(f"unexpected status: {result.final_status}", err=True)
    raise SystemExit(4)


# ---------------------------------------------------------------- propose


@canon_group.command("propose")
@click.option(
    "--strategy",
    type=click.Choice(["deterministic", "balanced"]),
    default="deterministic",
    show_default=True,
    help="Proposal strategy. 'balanced' adds embedding KNN + LLM verify slots "
    "(real model wiring lands at gateway boot in slice 5).",
)
@click.option(
    "--threshold",
    type=float,
    default=0.6,
    show_default=True,
    help="n-gram Jaccard threshold (0..1) for clustering similar concept ids.",
)
def propose_cmd(strategy: str, threshold: float) -> None:
    """Generate review-candidate merge proposals."""

    async def _go(service, _storage):
        if strategy == "balanced":
            proposer = BalancedProposer(
                index=service._index,
                store=service._store,
                threshold=threshold,
                decisions=service._decisions,
            )
        else:
            proposer = DeterministicProposer(
                index=service._index,
                store=service._store,
                threshold=threshold,
            )
        return await proposer.generate()

    paths_created = _run_with_service(_go)
    if not paths_created:
        click.echo("No new proposals.")
        return
    click.echo(f"Generated {len(paths_created)} proposal(s):")
    for p in paths_created:
        click.echo(f"  {p}")


@canon_group.command("list-proposals")
@click.option(
    "--status",
    type=click.Choice(["pending", "accepted", "rejected", "expired", "superseded"]),
    default="pending",
    show_default=True,
)
@click.option("--kind", default=None, help="Optional kind filter (e.g. merge-concepts).")
def list_proposals_cmd(status: str, kind: str | None) -> None:
    """List proposal notes by status / kind."""

    async def _go(service, _storage):
        return await service._index.list_proposals(status=status, kind=kind)

    proposals = _run_with_service(_go)
    if not proposals:
        click.echo(f"No proposals with status={status!r}.")
        return
    for p in proposals:
        click.echo(
            f"  {p.path}  ({p.kind}, score={p.proposal_score:.2f}, linked={len(p.action_drafts)})"
        )


@canon_group.command("review")
@click.argument("proposal_path")
@click.option(
    "--accept",
    "decision",
    flag_value="accept",
    help="Apply linked action drafts and mark proposal accepted.",
)
@click.option(
    "--reject",
    "decision",
    flag_value="reject",
    help="Mark proposal rejected (linked drafts left alone).",
)
@click.option("--reason", default=None, help="Optional reason for rejection.")
@click.option(
    "--as-cannot-link",
    "as_cannot_link",
    is_flag=True,
    help=(
        "After rejecting, persist a cannot-link decision between the proposal's "
        "merge subjects so future proposers learn from the decision (Handoff §8.1)."
    ),
)
@click.option(
    "--confidence",
    type=float,
    default=0.95,
    show_default=True,
    help="base_confidence for the cannot-link decision when --as-cannot-link is set.",
)
def review_cmd(
    proposal_path: str,
    decision: str | None,
    reason: str | None,
    as_cannot_link: bool,
    confidence: float,
) -> None:
    """Review a proposal — print evidence, then optionally accept/reject."""

    async def _summary(service, storage):
        proposal = await service._store.read_proposal(proposal_path)
        return proposal, storage

    proposal, _storage = _run_with_service(_summary)
    if proposal is None:
        click.echo(f"proposal not found: {proposal_path}", err=True)
        raise SystemExit(2)

    click.echo(f"=== Proposal: {proposal.kind} ({proposal.status}) ===")
    click.echo(f"strategy: {proposal.strategy}  generator: {proposal.generator}")
    click.echo(f"score: {proposal.proposal_score:.2f}")
    click.echo("Evidence:")
    for ev in proposal.evidence:
        payload = ev.get("payload", {})
        click.echo(f"  - {ev.get('kind')}: {payload}  ({ev.get('source')})")
    click.echo("Linked action drafts:")
    for ap in proposal.action_drafts:
        click.echo(f"  - {ap}")

    if decision is None:
        # Read-only review: nothing else to do.
        if as_cannot_link:
            click.echo("--as-cannot-link requires --reject (or --accept).", err=True)
            raise SystemExit(2)
        return
    if proposal.status != "pending":
        click.echo(f"cannot {decision}: proposal status is {proposal.status!r}", err=True)
        raise SystemExit(3)
    if as_cannot_link and decision != "reject":
        click.echo("--as-cannot-link only applies with --reject.", err=True)
        raise SystemExit(2)

    async def _decide(service, _storage):
        if decision == "accept":
            return await service.accept_proposal(proposal_path, actor="cli")
        return await service.reject_proposal(proposal_path, actor="cli", reason=reason)

    outcome = _run_with_service(_decide)
    if decision == "accept":
        all_applied = all(r.final_status == "applied" for r in outcome)
        if all_applied:
            click.echo(f"accepted. {len(outcome)} action(s) applied.")
        else:
            click.echo("partial: some linked actions did not apply.")
            for r in outcome:
                click.echo(f"  {r.action_path} -> {r.final_status}")
            raise SystemExit(4)
        return

    click.echo("rejected.")
    if not as_cannot_link:
        return

    # Extract subjects from the linked merge action draft and persist a
    # cannot-link decision between them.
    subjects = _subjects_from_proposal(proposal)
    if subjects is None:
        click.echo(
            "could not derive subjects for cannot-link from proposal; "
            "create the decision manually with `bsage canon decide`.",
            err=True,
        )
        return

    decision_path = _build_decision_path("cannot-link", "-".join(subjects))

    async def _persist(service, _storage):
        action_path = await service.create_action_draft(
            kind="create-decision",
            params={
                "decision_path": decision_path,
                "subjects": list(subjects),
                "base_confidence": float(confidence),
                "maturity": "seedling",
            },
        )
        return await service.apply_action(action_path, actor="cli")

    result = _run_with_service(_persist)
    if result.final_status == "applied":
        click.echo(f"cannot-link decision recorded: {decision_path}")
    else:
        click.echo(f"failed to record cannot-link decision: {result.final_status}", err=True)
        raise SystemExit(5)


def _subjects_from_proposal(proposal: Any) -> tuple[str, str] | None:
    """Best-effort extraction of (a, b) from a merge-concepts proposal."""
    if proposal.kind != "merge-concepts" or not proposal.action_drafts:
        return None
    # Decision subjects come from the linked action draft frontmatter
    # — but the proposal evidence already names the canonical + alias pair.
    canonical: str | None = None
    merge: str | None = None
    for ev in proposal.evidence:
        payload = ev.get("payload") or {}
        if ev.get("kind") == "alias_exact":
            canonical = canonical or payload.get("matches_canonical")
            merge = merge or payload.get("alias")
            if canonical and merge:
                break
        if ev.get("kind") == "frequency":
            canonical = canonical or payload.get("canonical")
            merges = list(payload.get("merge_uses") or {})
            if merges:
                merge = merge or merges[0]
    if canonical and merge:
        return (canonical, merge)
    return None


def _build_decision_path(kind: str, slug: str) -> str:
    """Generate a decisions/<kind>/<timestamp>-<slug>.md path."""
    if not canon_paths.is_valid_concept_id(slug):
        # Fall back: replace invalid chars
        slug = "-".join(part for part in slug.split("-") if part) or "decision"
    return canon_paths.build_decision_path(kind, datetime.now(), slug)


# ---------------------------------------------------------- decisions/policies


@canon_group.command("bootstrap-policies")
def bootstrap_policies_cmd() -> None:
    """Idempotently write the three default policy fixtures (Handoff §8.3-8.5)."""

    async def _go(service, _storage):
        return await service._policies.bootstrap_defaults()

    created = _run_with_service(_go)
    if not created:
        click.echo("Default policies already present.")
        return
    click.echo(f"Created {len(created)} default policy file(s):")
    for p in created:
        click.echo(f"  {p}")


@canon_group.command("decide")
@click.argument("kind", type=click.Choice(["cannot-link", "must-link"]))
@click.option(
    "--subject",
    "subjects",
    multiple=True,
    required=True,
    help="Subject concept id (repeatable; usually exactly two).",
)
@click.option(
    "--confidence",
    type=float,
    default=0.95,
    show_default=True,
    help="base_confidence (0..1).",
)
@click.option(
    "--maturity",
    type=click.Choice(["seedling", "budding", "evergreen"]),
    default="seedling",
    show_default=True,
)
@click.option(
    "--decay-profile",
    type=click.Choice(["definitional", "semantic", "episodic", "procedural", "affective"]),
    default=None,
    help="Override decay profile (default: definitional for cannot-link, semantic for must-link).",
)
def decide_cmd(
    kind: str,
    subjects: tuple[str, ...],
    confidence: float,
    maturity: str,
    decay_profile: str | None,
) -> None:
    """Persist a cannot-link or must-link decision."""
    if not subjects:
        raise click.BadParameter("at least one --subject required")
    slug = "-".join(subjects) or "decision"
    decision_path = _build_decision_path(kind, slug)

    async def _go(service, _storage):
        params: dict[str, Any] = {
            "decision_path": decision_path,
            "subjects": list(subjects),
            "base_confidence": float(confidence),
            "maturity": maturity,
        }
        if decay_profile is not None:
            params["decay_profile"] = decay_profile
        action_path = await service.create_action_draft(kind="create-decision", params=params)
        return await service.apply_action(action_path, actor="cli")

    result = _run_with_service(_go)
    if result.final_status == "applied":
        click.echo(f"applied. {decision_path}")
        return
    click.echo(f"{result.final_status}: see {result.action_path}", err=True)
    raise SystemExit(2)


@canon_group.command("list-decisions")
@click.option(
    "--kind",
    type=click.Choice(["cannot-link", "must-link"]),
    default=None,
    help="Optional kind filter.",
)
@click.option(
    "--status",
    type=click.Choice(["active", "superseded", "retracted", "expired"]),
    default="active",
    show_default=True,
)
def list_decisions_cmd(kind: str | None, status: str) -> None:
    """List decision notes by kind / status."""

    async def _go(service, _storage):
        return await service._index.list_decisions(kind=kind, status=status)

    decisions = _run_with_service(_go)
    if not decisions:
        click.echo(f"No decisions with status={status!r}.")
        return
    for d in decisions:
        subjects = " + ".join(d.subjects)
        click.echo(
            f"  {d.path}  ({d.kind}, {subjects}, confidence={d.base_confidence:.2f}, "
            f"profile={d.decay_profile})"
        )


@canon_group.command("expire")
def expire_cmd() -> None:
    """Expire stale draft/pending actions and pending proposals (Handoff §15.3)."""

    async def _go(service, _storage):
        return await service.expire_stale()

    result = _run_with_service(_go)
    click.echo(
        f"expired {len(result.expired_actions)} action(s), "
        f"{len(result.expired_proposals)} proposal(s)."
    )
    for path in result.expired_actions:
        click.echo(f"  action  {path}")
    for path in result.expired_proposals:
        click.echo(f"  proposal {path}")


@canon_group.command("lint")
@click.option(
    "--severity",
    type=click.Choice(["all", "warning", "error"]),
    default="all",
    show_default=True,
    help="Filter findings by severity.",
)
def lint_cmd(severity: str) -> None:
    """Run canon lint detectors (orphan tags, alias collisions, redirect anomalies)."""
    from bsage.garden.canonicalization.lint import run_lint

    async def _go(service, _storage):
        return await run_lint(service._index, service._store)

    report = _run_with_service(_go)
    findings = report.findings
    if severity != "all":
        findings = [f for f in findings if f.severity == severity]
    if not findings:
        click.echo("clean — no findings.")
        return
    click.echo(
        f"{len(findings)} finding(s) — orphan_tags={report.orphan_tag_count}, "
        f"alias_collisions={report.alias_collision_count}, "
        f"redirect_anomalies={report.redirect_anomaly_count}"
    )
    for f in findings:
        click.echo(f"  [{f.severity}] {f.kind}: {f.payload}")
    has_error = any(f.severity == "error" for f in findings)
    if has_error:
        raise SystemExit(1)


@canon_group.command("decision-stats")
def decision_stats_cmd() -> None:
    """Summarize active decisions + average effective strength."""

    async def _go(service, _storage):
        memory = service._decisions
        if memory is None:
            return None
        cannot = await memory.list_active_cannot_link()
        must = await memory.list_active_must_link()
        now = datetime.now()
        avg_cannot = (
            sum(memory.effective_strength(d, now=now) for d in cannot) / len(cannot)
            if cannot
            else 0.0
        )
        avg_must = (
            sum(memory.effective_strength(d, now=now) for d in must) / len(must) if must else 0.0
        )
        return {
            "cannot_link": (len(cannot), avg_cannot),
            "must_link": (len(must), avg_must),
        }

    stats = _run_with_service(_go)
    if stats is None:
        click.echo("Decision memory not wired.", err=True)
        raise SystemExit(2)
    cl_n, cl_avg = stats["cannot_link"]
    ml_n, ml_avg = stats["must_link"]
    click.echo(f"cannot-link decisions: {cl_n} (effective avg {cl_avg:.2f})")
    click.echo(f"must-link decisions: {ml_n} (effective avg {ml_avg:.2f})")
