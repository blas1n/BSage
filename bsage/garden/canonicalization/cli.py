"""``bsage canon`` — slice-1 CLI shim (Vertical_Slices §2 demo)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import click
import structlog

from bsage.core.config import get_settings
from bsage.garden.canonicalization import paths as canon_paths
from bsage.garden.canonicalization.lock import AsyncIOMutationLock
from bsage.garden.canonicalization.service import CanonicalizationService
from bsage.garden.canonicalization.store import NoteStore
from bsage.garden.storage import FileSystemStorage

logger = structlog.get_logger(__name__)


def _build_service(vault_path: Path | None = None) -> CanonicalizationService:
    if vault_path is None:
        settings = get_settings()
        vault_path = Path(settings.vault_path).expanduser().resolve()
    vault_path.mkdir(parents=True, exist_ok=True)
    storage = FileSystemStorage(vault_path)
    return CanonicalizationService(
        store=NoteStore(storage),
        lock=AsyncIOMutationLock(),
    )


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
    service = _build_service()
    params: dict[str, Any] = {"concept": concept, "title": title}
    if aliases:
        params["aliases"] = list(aliases)
    path = asyncio.run(service.create_action_draft(kind="create-concept", params=params))
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

    service = _build_service()
    params: dict[str, Any] = {
        "changes": [
            {
                "path": garden_path,
                "remove_tags": list(remove_tags),
                "add_tags": list(add_tags),
            }
        ]
    }
    path = asyncio.run(
        service.create_action_draft(kind="retag-notes", params=params, slug=derived_slug)
    )
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
    service = _build_service()
    result = asyncio.run(service.apply_action(action_path, actor="cli"))

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
