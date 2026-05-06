"""NoteStore — typed wrapper over StorageBackend (Class_Diagram §5).

Reuses ``markdown_utils.extract_frontmatter`` / ``extract_title`` /
``body_after_frontmatter`` and ``note.build_frontmatter`` (per Class_Diagram §10).
Handles ISO 8601 datetime serialization (Handoff §2) and frontmatter shape
discipline (Handoff §0.2 — path/frontmatter have different jobs).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from bsage.garden.canonicalization import models, paths
from bsage.garden.markdown_utils import (
    body_after_frontmatter,
    extract_frontmatter,
    extract_title,
)
from bsage.garden.note import build_frontmatter
from bsage.garden.storage import StorageBackend


def _iso(dt: datetime) -> str:
    """ISO 8601 with timezone where present (Handoff §2)."""
    return dt.isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    msg = f"unsupported datetime value: {value!r}"
    raise TypeError(msg)


def _drop_nones(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively drop None entries so YAML stays clean."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            out[k] = _drop_nones(v)
        else:
            out[k] = v
    return out


def _serialize_record(record: Any) -> dict[str, Any]:
    """Serialize a nested dataclass record, converting datetime → ISO."""
    raw = asdict(record)
    return {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in raw.items()}


class NoteStore:
    """Typed read/write helpers for canonicalization notes.

    Slice 1 implements concepts (active) + actions + garden tag mutation only.
    Proposals/decisions/policies/tombstones come in later slices.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    # ------------------------------------------------------------------ concepts

    async def concept_exists(self, concept_id: str) -> bool:
        return await self._storage.exists(paths.active_concept_path(concept_id))

    async def read_concept(self, concept_id: str) -> models.ConceptEntry | None:
        path = paths.active_concept_path(concept_id)
        if not await self._storage.exists(path):
            return None
        text = await self._storage.read(path)
        fm = extract_frontmatter(text)
        return models.ConceptEntry(
            concept_id=concept_id,
            path=path,
            display=extract_title(text),
            aliases=list(fm.get("aliases") or []),
            created_at=_parse_iso(fm.get("created_at")) or datetime.min,
            updated_at=_parse_iso(fm.get("updated_at")) or datetime.min,
            source_action=fm.get("source_action"),
        )

    async def write_concept(
        self,
        entry: models.ConceptEntry,
        initial_body: str | None = None,
    ) -> None:
        # Handoff §3.1: aliases / created_at / updated_at / source_action only.
        # Forbidden: status, concept_id, canonical_tag, display, bsage_role, graph_scope.
        fm: dict[str, Any] = {
            "created_at": _iso(entry.created_at),
            "updated_at": _iso(entry.updated_at),
        }
        if entry.aliases:
            fm["aliases"] = list(entry.aliases)
        if entry.source_action is not None:
            fm["source_action"] = entry.source_action

        body_lines = [f"# {entry.display}", ""]
        if initial_body:
            body_lines.append(initial_body.rstrip() + "\n")
        body = "\n".join(body_lines)
        text = build_frontmatter(fm) + body
        await self._storage.write(entry.path, text)

    # ------------------------------------------------------------------- actions

    async def read_action(self, path: str) -> models.ActionEntry | None:
        if not await self._storage.exists(path):
            return None
        text = await self._storage.read(path)
        fm = extract_frontmatter(text)
        kind = self._action_kind_from_path(path)

        validation_fm = fm.get("validation") or {}
        scoring_fm = fm.get("scoring") or {}
        permission_fm = fm.get("permission") or {}
        execution_fm = fm.get("execution") or {}

        return models.ActionEntry(
            path=path,
            kind=kind,
            status=fm.get("status", "draft"),
            action_schema_version=fm.get("action_schema_version", ""),
            params=dict(fm.get("params") or {}),
            created_at=_parse_iso(fm.get("created_at")) or datetime.min,
            updated_at=_parse_iso(fm.get("updated_at")) or datetime.min,
            expires_at=_parse_iso(fm.get("expires_at")) or datetime.min,
            source_proposal=fm.get("source_proposal"),
            freshness=dict(fm.get("freshness") or {}),
            validation=models.ValidationResult(
                status=validation_fm.get("status", "not_run"),
                hard_blocks=list(validation_fm.get("hard_blocks") or []),
            ),
            scoring=models.ScoreResult(
                status=scoring_fm.get("status", "not_run"),
                stability_score=scoring_fm.get("stability_score"),
                scorer_version=scoring_fm.get("scorer_version"),
                policy_profile_path=scoring_fm.get("policy_profile_path"),
                risk_reasons=list(scoring_fm.get("risk_reasons") or []),
                deterministic_evidence=list(scoring_fm.get("deterministic_evidence") or []),
                model_evidence=list(scoring_fm.get("model_evidence") or []),
                human_evidence=list(scoring_fm.get("human_evidence") or []),
            ),
            permission=models.PermissionRecord(
                safe_mode=permission_fm.get("safe_mode"),
                decision=permission_fm.get("decision"),
                actor=permission_fm.get("actor"),
                decided_at=_parse_iso(permission_fm.get("decided_at")),
            ),
            execution=models.ExecutionRecord(
                status=execution_fm.get("status", "not_run"),
                applied_at=_parse_iso(execution_fm.get("applied_at")),
                error=execution_fm.get("error"),
            ),
            affected_paths=list(fm.get("affected_paths") or []),
            supersedes=list(fm.get("supersedes") or []),
            superseded_by=fm.get("superseded_by"),
            evidence=list(fm.get("evidence") or []),
        )

    async def write_action(self, entry: models.ActionEntry, body: str = "") -> None:
        # Handoff §0.2: kind is path-derived. Do NOT write action_type.
        fm: dict[str, Any] = {
            "status": entry.status,
            "created_at": _iso(entry.created_at),
            "updated_at": _iso(entry.updated_at),
            "expires_at": _iso(entry.expires_at),
            "action_schema_version": entry.action_schema_version,
            "params": entry.params,
            "freshness": entry.freshness,
            "validation": _serialize_record(entry.validation),
            "scoring": _serialize_record(entry.scoring),
            "permission": _drop_nones(_serialize_record(entry.permission)),
            "execution": _drop_nones(_serialize_record(entry.execution)),
            "affected_paths": list(entry.affected_paths),
            "supersedes": list(entry.supersedes),
            "superseded_by": entry.superseded_by,
            "evidence": list(entry.evidence),
        }
        if entry.source_proposal is not None:
            fm["source_proposal"] = entry.source_proposal

        text = build_frontmatter(fm) + (body or "")
        await self._storage.write(entry.path, text)

    async def list_existing_action_paths(self, action_kind: str) -> set[str]:
        return set(await self._storage.list_files(f"actions/{action_kind}", "*.md"))

    # ----------------------------------------------------------------- proposals

    async def read_proposal(self, path: str) -> models.ProposalEntry | None:
        if not await self._storage.exists(path):
            return None
        text = await self._storage.read(path)
        fm = extract_frontmatter(text)
        kind = self._proposal_kind_from_path(path)
        return models.ProposalEntry(
            path=path,
            kind=kind,
            status=fm.get("status", "pending"),
            strategy=fm.get("strategy", ""),
            generator=fm.get("generator", ""),
            generator_version=fm.get("generator_version", ""),
            proposal_score=float(fm.get("proposal_score") or 0.0),
            created_at=_parse_iso(fm.get("created_at")) or datetime.min,
            updated_at=_parse_iso(fm.get("updated_at")) or datetime.min,
            expires_at=_parse_iso(fm.get("expires_at")) or datetime.min,
            freshness=dict(fm.get("freshness") or {}),
            evidence=list(fm.get("evidence") or []),
            affected_paths=list(fm.get("affected_paths") or []),
            action_drafts=list(fm.get("action_drafts") or []),
            result_actions=list(fm.get("result_actions") or []),
        )

    async def write_proposal(self, entry: models.ProposalEntry, body: str = "") -> None:
        # Handoff §0.2: proposal kind is path-derived. Do NOT write proposal_type.
        # Handoff §5: proposals MUST NOT contain executable params.
        fm: dict[str, Any] = {
            "status": entry.status,
            "created_at": _iso(entry.created_at),
            "updated_at": _iso(entry.updated_at),
            "expires_at": _iso(entry.expires_at),
            "strategy": entry.strategy,
            "generator": entry.generator,
            "generator_version": entry.generator_version,
            "proposal_score": entry.proposal_score,
            "freshness": entry.freshness,
            "evidence": list(entry.evidence),
            "affected_paths": list(entry.affected_paths),
            "action_drafts": list(entry.action_drafts),
            "result_actions": list(entry.result_actions),
        }
        text = build_frontmatter(fm) + (body or "")
        await self._storage.write(entry.path, text)

    async def list_existing_proposal_paths(self, proposal_kind: str) -> set[str]:
        return set(await self._storage.list_files(f"proposals/{proposal_kind}", "*.md"))

    # ---------------------------------------------------------------- tombstones

    async def write_tombstone(
        self,
        old_id: str,
        merged_into: str,
        merged_at: datetime,
        source_action: str | None = None,
        display: str | None = None,
    ) -> str:
        """Create ``concepts/merged/<old-id>.md`` (Handoff §3.2)."""
        path = f"concepts/merged/{old_id}.md"
        fm: dict[str, Any] = {
            "merged_into": merged_into,
            "merged_at": _iso(merged_at),
        }
        if source_action is not None:
            fm["source_action"] = source_action
        body = f"# {display or old_id}\n"
        text = build_frontmatter(fm) + body
        await self._storage.write(path, text)
        return path

    async def delete_active_concept(self, concept_id: str) -> None:
        await self._storage.delete(f"concepts/active/{concept_id}.md")

    async def list_garden_paths(self) -> list[str]:
        """All garden notes across maturity folders."""
        return list(await self._storage.list_files("garden", "*.md"))

    # ------------------------------------------------------------------- garden

    async def read_garden_tags(self, garden_path: str) -> list[str]:
        if not await self._storage.exists(garden_path):
            msg = f"garden note not found: {garden_path}"
            raise FileNotFoundError(msg)
        text = await self._storage.read(garden_path)
        fm = extract_frontmatter(text)
        return list(fm.get("tags") or [])

    async def set_garden_tags(self, garden_path: str, tags: list[str]) -> None:
        """Replace ``tags`` frontmatter on a garden note (Handoff §7.6)."""
        if await self._storage.exists(garden_path):
            text = await self._storage.read(garden_path)
        else:
            text = ""
        fm = extract_frontmatter(text)
        body = body_after_frontmatter(text)
        fm["tags"] = list(tags)
        # If body is empty (no frontmatter present originally), ensure clean output
        new_text = build_frontmatter(fm) + body
        await self._storage.write(garden_path, new_text)

    # ------------------------------------------------------------------- helpers

    @staticmethod
    def _action_kind_from_path(path: str) -> str:
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != "actions":
            msg = f"not an action path: {path!r}"
            raise ValueError(msg)
        return parts[1]

    @staticmethod
    def _proposal_kind_from_path(path: str) -> str:
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != "proposals":
            msg = f"not a proposal path: {path!r}"
            raise ValueError(msg)
        return parts[1]
