"""Vault migrations for the dynamic-ontology refactor.

The CLI entry point :func:`migrate_flatten_vault` walks an existing vault,
moves notes from legacy entity-type folders (``ideas/``, ``insights/``,
``projects/``, ``garden/idea/``, ...) into the maturity-based layout
(``garden/seedling/`` by default; preserved when a note already declares
``maturity:`` in its frontmatter), demotes the legacy ``type:`` field
into a tag, and stamps each migrated file with ``_pre_migration_path``
so a future ``--revert`` can put everything back.

Stayed factored as a library function so unit tests can drive it without
spinning up the click runner — the CLI wrapper is a thin shim in
``bsage._cli_legacy``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Folders the migrator walks looking for notes to move. Order doesn't
# matter; ``garden/seedling`` etc. are skipped.
_LEGACY_TOPLEVEL_FOLDERS: tuple[str, ...] = (
    "ideas",
    "insights",
    "projects",
    "people",
    "events",
    "tasks",
    "facts",
    "preferences",
    "organizations",
    "tools",
    "concepts",
)
_LEGACY_GARDEN_SUBFOLDERS: tuple[str, ...] = (
    "idea",
    "insight",
    "project",
    "person",
    "event",
    "task",
    "fact",
    "preference",
    "organization",
    "tool",
    "concept",
)
_MATURITY_VALUES: frozenset[str] = frozenset({"seedling", "budding", "evergreen"})


@dataclass
class MigrationPlanItem:
    """One file the migrator would touch."""

    src: Path
    dst: Path
    legacy_type: str | None
    new_tags: list[str]


@dataclass
class MigrationPlan:
    """The aggregate dry-run output."""

    moves: list[MigrationPlanItem] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.moves)


def plan_flatten(vault_root: Path) -> MigrationPlan:
    """Compute the migration plan without touching any files."""
    plan = MigrationPlan()
    # Track destinations claimed by earlier entries — needed because two
    # legacy paths (e.g. ``ideas/dup.md`` and ``insights/dup.md``) both
    # want to land at the same ``garden/seedling/dup.md`` slot.
    claimed: set[Path] = set()
    for src in _iter_legacy_notes(vault_root):
        try:
            entry = _plan_one(src, vault_root, claimed=claimed)
        except (OSError, yaml.YAMLError):
            plan.skipped.append(src)
            continue
        if entry is None:
            plan.skipped.append(src)
            continue
        claimed.add(entry.dst)
        plan.moves.append(entry)
    return plan


def apply_flatten(vault_root: Path, *, backup: bool = True) -> MigrationPlan:
    """Execute the plan. Optionally snapshots the vault into ``.bsage`` first."""
    plan = plan_flatten(vault_root)
    if backup:
        _backup(vault_root, "flatten")
    for entry in plan.moves:
        _apply_one(entry)
    return plan


def revert_flatten(vault_root: Path) -> MigrationPlan:
    """Walk the maturity tree and undo any file that carries ``_pre_migration_path``."""
    plan = MigrationPlan()
    maturity_dirs = [vault_root / "garden" / m for m in _MATURITY_VALUES]
    for base in maturity_dirs:
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            try:
                fm, body = _read_frontmatter(path)
            except (OSError, yaml.YAMLError):
                plan.skipped.append(path)
                continue
            pre_path = fm.get("_pre_migration_path") if isinstance(fm, dict) else None
            if not pre_path:
                continue
            dst = vault_root / pre_path
            entry = MigrationPlanItem(src=path, dst=dst, legacy_type=None, new_tags=[])
            try:
                _revert_one(path, dst, fm, body)
            except OSError:
                plan.skipped.append(path)
                continue
            plan.moves.append(entry)
    return plan


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _iter_legacy_notes(vault_root: Path):
    """Yield every ``.md`` under a known legacy folder."""
    for name in _LEGACY_TOPLEVEL_FOLDERS:
        base = vault_root / name
        if base.is_dir():
            yield from base.rglob("*.md")
    garden_root = vault_root / "garden"
    if garden_root.is_dir():
        for name in _LEGACY_GARDEN_SUBFOLDERS:
            base = garden_root / name
            if base.is_dir():
                yield from base.rglob("*.md")


def _plan_one(
    src: Path, vault_root: Path, *, claimed: set[Path] | None = None
) -> MigrationPlanItem | None:
    """Build a single MigrationPlanItem for ``src``."""
    claimed = claimed or set()
    fm, _body = _read_frontmatter(src)
    if fm is None:
        return None
    maturity = (fm.get("maturity") if isinstance(fm, dict) else None) or "seedling"
    if maturity not in _MATURITY_VALUES:
        maturity = "seedling"
    legacy_type = fm.get("type") if isinstance(fm, dict) else None
    raw_tags = fm.get("tags", []) if isinstance(fm, dict) else []
    if not isinstance(raw_tags, list):
        raw_tags = []
    new_tags: list[str] = list(raw_tags)
    if isinstance(legacy_type, str) and legacy_type and legacy_type not in new_tags:
        new_tags.append(legacy_type)

    dst_dir = vault_root / "garden" / maturity
    dst = dst_dir / src.name

    def _taken(path: Path) -> bool:
        return path in claimed or (path.exists() and path != src)

    if _taken(dst):
        # Slug collision: either with a file already on disk or with an
        # earlier plan entry destined for the same slot.
        stem = src.stem
        for n in range(1, 1000):
            candidate = dst_dir / f"{stem}_{n:03d}.md"
            if not _taken(candidate):
                dst = candidate
                break
    return MigrationPlanItem(src=src, dst=dst, legacy_type=legacy_type, new_tags=new_tags)


def _apply_one(entry: MigrationPlanItem) -> None:
    fm, body = _read_frontmatter(entry.src)
    if fm is None:
        fm = {}
    fm = dict(fm) if isinstance(fm, dict) else {}
    fm["maturity"] = fm.get("maturity") or "seedling"
    if entry.new_tags:
        fm["tags"] = entry.new_tags
    if entry.legacy_type:
        fm.pop("type", None)
    # Vault-relative original location, used by ``--revert``. Always
    # stored as a forward-slash path even on Windows.
    rel = entry.src.relative_to(_find_vault_root(entry.src))
    fm["_pre_migration_path"] = str(rel).replace("\\", "/")

    entry.dst.parent.mkdir(parents=True, exist_ok=True)
    entry.dst.write_text(_serialise(fm, body), encoding="utf-8")
    if entry.dst != entry.src:
        entry.src.unlink()


def _revert_one(src: Path, dst: Path, fm: dict[str, Any], body: str) -> None:
    fm = dict(fm)
    fm.pop("_pre_migration_path", None)
    # Restore the legacy ``type:`` if we can infer it from the dst path
    # (e.g. ``ideas/foo.md`` → type: idea). Keep the frontmatter free of
    # forced injection — only set ``type:`` when the legacy folder
    # naming makes the kind obvious.
    legacy_singular = _legacy_type_from_path(dst)
    if legacy_singular and "type" not in fm:
        fm["type"] = legacy_singular
        # And drop the equivalent tag we appended at apply time.
        if "tags" in fm and isinstance(fm["tags"], list):
            fm["tags"] = [t for t in fm["tags"] if t != legacy_singular]
            if not fm["tags"]:
                fm.pop("tags")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_serialise(fm, body), encoding="utf-8")
    src.unlink()


def _legacy_type_from_path(path: Path) -> str | None:
    """``ideas/foo.md`` → ``"idea"``; ``garden/insight/x.md`` → ``"insight"``."""
    parts = path.parts
    for top in _LEGACY_TOPLEVEL_FOLDERS:
        if top in parts:
            return top.rstrip("s") if top.endswith("s") else top
    if "garden" in parts:
        idx = parts.index("garden")
        if idx + 1 < len(parts) and parts[idx + 1] in _LEGACY_GARDEN_SUBFOLDERS:
            return parts[idx + 1]
    return None


def _read_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, text
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return None, text
    fm_text = text[4:closing]
    body = text[closing + 5 :]
    parsed = yaml.safe_load(fm_text)
    if not isinstance(parsed, dict):
        return None, body
    return parsed, body


def _serialise(fm: dict[str, Any], body: str) -> str:
    dumped = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n{body}"


def _find_vault_root(path: Path) -> Path:
    """Walk up from ``path`` until we find a directory that looks like a vault.

    Heuristic: presence of ``.bsage/`` or any of the known top-level
    folders (``garden`` / ``seeds`` / a legacy entity folder). This is
    used for stamping a vault-relative ``_pre_migration_path`` even
    when the caller didn't pass the vault root in.
    """
    candidate = path.parent
    while candidate != candidate.parent:
        if (candidate / ".bsage").exists():
            return candidate
        if (candidate / "garden").exists() or (candidate / "seeds").exists():
            return candidate
        candidate = candidate.parent
    return path.parent


def _backup(vault_root: Path, label: str) -> Path:
    ts = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    backup_dir = vault_root / ".bsage" / f"migration-backup-{label}-{ts}"
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    # Snapshot only the directories we'll touch — no need to copy seeds
    # or .bsage itself which would balloon the backup pointlessly.
    backup_dir.mkdir()
    for name in (*_LEGACY_TOPLEVEL_FOLDERS, "garden"):
        src = vault_root / name
        if src.is_dir():
            shutil.copytree(src, backup_dir / name, dirs_exist_ok=True)
    return backup_dir


__all__ = [
    "MigrationPlan",
    "MigrationPlanItem",
    "apply_flatten",
    "plan_flatten",
    "revert_flatten",
]
