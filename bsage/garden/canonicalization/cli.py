"""``bsage canon`` — CLI shim across slices 1-3."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import click
import structlog

from bsage.core.config import get_settings
from bsage.garden.canonicalization import paths as canon_paths
from bsage.garden.canonicalization.index import InMemoryCanonicalizationIndex
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.proposals import DeterministicProposer
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
    service = CanonicalizationService(
        store=NoteStore(storage),
        lock=AsyncIOMutationLock(),
        index=index,
        resolver=TagResolver(index=index),
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
    type=click.Choice(["deterministic"]),
    default="deterministic",
    show_default=True,
    help="Proposal generation strategy. Slice 3 ships 'deterministic' only.",
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
def review_cmd(proposal_path: str, decision: str | None, reason: str | None) -> None:
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
        return
    if proposal.status != "pending":
        click.echo(f"cannot {decision}: proposal status is {proposal.status!r}", err=True)
        raise SystemExit(3)

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
    else:
        click.echo("rejected.")
