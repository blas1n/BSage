"""REST routes for canonicalization (Handoff §15.1).

Mounted under ``/api/canonicalization/...``. All mutation goes through
the core ``CanonicalizationService`` so REST and MCP share the same
typed-action contract.

Authz uses the existing ``require_bsage_permission`` decorators, with
permission strings matching the four canonicalization permission
surfaces from Handoff §16:

- ``bsage.canonicalization.read``    — list/get notes, list policies
- ``bsage.canonicalization.draft``   — propose, draft, validate, score
- ``bsage.canonicalization.apply``   — apply, approve, reject, expire
- ``bsage.canonicalization.govern``  — create-decision, update-policy
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bsage.gateway.authz import require_bsage_permission

if TYPE_CHECKING:
    from bsage.gateway.dependencies import AppState

logger = structlog.get_logger(__name__)


# ----------------------------------------------------------- Pydantic models


class ResolveTagBody(BaseModel):
    raw_tag: str = Field(..., description="Raw tag emitted by ingest/LLM.")
    raw_source: str | None = None
    auto_apply: bool = True


class ProposalGenerateBody(BaseModel):
    strategy: str = Field(default="deterministic", pattern="^(deterministic|balanced)$")
    threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class ActionDraftBody(BaseModel):
    kind: str
    params: dict[str, Any]
    slug: str | None = None
    source_proposal: str | None = None


class ActionPathBody(BaseModel):
    action_path: str


class RejectActionBody(BaseModel):
    action_path: str
    reason: str | None = None


class ExpireBody(BaseModel):
    pass  # placeholder for future filter args


# ----------------------------------------------------------- helpers


def _proposal_to_dict(p: Any) -> dict[str, Any]:
    return {
        "path": p.path,
        "kind": p.kind,
        "status": p.status,
        "strategy": p.strategy,
        "generator": p.generator,
        "proposal_score": p.proposal_score,
        "evidence": list(p.evidence),
        "action_drafts": list(p.action_drafts),
        "result_actions": list(p.result_actions),
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
        "expires_at": p.expires_at.isoformat(),
    }


def _action_to_dict(a: Any) -> dict[str, Any]:
    return {
        "path": a.path,
        "kind": a.kind,
        "status": a.status,
        "params": a.params,
        "stability_score": a.scoring.stability_score,
        "risk_reasons": list(a.scoring.risk_reasons),
        "deterministic_evidence": list(a.scoring.deterministic_evidence),
        "model_evidence": list(a.scoring.model_evidence),
        "human_evidence": list(a.scoring.human_evidence),
        "affected_paths": list(a.affected_paths),
        "source_proposal": a.source_proposal,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
        "expires_at": a.expires_at.isoformat(),
    }


def _concept_to_dict(c: Any) -> dict[str, Any]:
    return {
        "concept_id": c.concept_id,
        "path": c.path,
        "display": c.display,
        "aliases": list(c.aliases),
        "source_action": c.source_action,
    }


def _tombstone_to_dict(t: Any) -> dict[str, Any]:
    return {
        "old_id": t.old_id,
        "path": t.path,
        "merged_into": t.merged_into,
        "merged_at": t.merged_at.isoformat() if t.merged_at else None,
    }


def _deprecated_to_dict(d: Any) -> dict[str, Any]:
    return {
        "concept_id": d.concept_id,
        "path": d.path,
        "deprecated_at": d.deprecated_at.isoformat() if d.deprecated_at else None,
        "replacement": d.replacement,
    }


def _policy_to_dict(p: Any) -> dict[str, Any]:
    return {
        "path": p.path,
        "kind": p.kind,
        "status": p.status,
        "profile_name": p.profile_name,
        "priority": p.priority,
        "scope": dict(p.scope),
        "params": dict(p.params),
        "valid_from": p.valid_from.isoformat() if p.valid_from else None,
    }


# ----------------------------------------------------------- router factory


def create_canonicalization_router(state: AppState) -> APIRouter:
    """Build the /api/canonicalization router bound to ``state``."""
    _principal = state.get_current_user
    canon_read = require_bsage_permission("bsage.canonicalization.read", principal_dep=_principal)
    canon_draft = require_bsage_permission("bsage.canonicalization.draft", principal_dep=_principal)
    canon_apply = require_bsage_permission("bsage.canonicalization.apply", principal_dep=_principal)
    # canon_govern is reserved for future endpoints (CreateDecision /
    # UpdatePolicy mutations exposed over REST). Wire when those land.

    router = APIRouter(
        prefix="/api/canonicalization",
        dependencies=[Depends(_principal)],
    )

    # ---------------------------------------------------- read

    @router.get("/concepts", dependencies=[Depends(canon_read)])
    async def list_concepts(
        status: str = Query(default="active", pattern="^(active|merged|deprecated)$"),
    ) -> dict[str, Any]:
        idx = state.canon_index
        if status == "active":
            entries = await idx.list_active_concepts()
            return {"items": [_concept_to_dict(e) for e in entries]}
        if status == "merged":
            tombstones = list(idx._tombstones.values())  # type: ignore[attr-defined]
            return {"items": [_tombstone_to_dict(t) for t in tombstones]}
        deprecated = list(idx._deprecated.values())  # type: ignore[attr-defined]
        return {"items": [_deprecated_to_dict(d) for d in deprecated]}

    @router.post("/resolve-tag", dependencies=[Depends(canon_draft)])
    async def resolve_tag(body: ResolveTagBody) -> dict[str, Any]:
        canonical = await state.canon_service.resolve_and_canonicalize(
            body.raw_tag, raw_source=body.raw_source, auto_apply=body.auto_apply
        )
        return {"raw_tag": body.raw_tag, "canonical": canonical}

    @router.get("/proposals", dependencies=[Depends(canon_read)])
    async def list_proposals(
        kind: str | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        proposals = await state.canon_index.list_proposals(status=status, kind=kind)
        return {"items": [_proposal_to_dict(p) for p in proposals]}

    @router.post("/proposals/generate", dependencies=[Depends(canon_draft)])
    async def generate_proposals(body: ProposalGenerateBody) -> dict[str, Any]:
        from bsage.garden.canonicalization.proposals import (
            BalancedProposer,
            DeterministicProposer,
        )

        if body.strategy == "balanced":
            proposer = BalancedProposer(
                index=state.canon_index,
                store=state.canon_service._store,  # noqa: SLF001
                threshold=body.threshold,
                decisions=state.canon_decisions,
                embedder=_embedder_callable(state),
                verifier=_verifier_callable(state),
            )
        else:
            proposer = DeterministicProposer(
                index=state.canon_index,
                store=state.canon_service._store,  # noqa: SLF001
                threshold=body.threshold,
            )
        paths = await proposer.generate()
        return {"strategy": body.strategy, "created": paths}

    @router.get("/note", dependencies=[Depends(canon_read)])
    async def get_note(path: str) -> dict[str, Any]:
        if not path.startswith(("concepts/", "proposals/", "actions/", "decisions/")):
            raise HTTPException(
                status_code=400,
                detail="path must be under concepts/proposals/actions/decisions/",
            )
        try:
            content = await state._canon_storage.read(path)  # noqa: SLF001
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="note not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": path, "content": content}

    @router.get("/actions", dependencies=[Depends(canon_read)])
    async def list_actions(
        kind: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        actions = await state.canon_index.list_actions(status=status, kind=kind)
        return {"items": [_action_to_dict(a) for a in actions]}

    # ---------------------------------------------------- draft

    @router.post("/actions/draft", dependencies=[Depends(canon_draft)])
    async def draft_action(body: ActionDraftBody) -> dict[str, Any]:
        try:
            path = await state.canon_service.create_action_draft(
                kind=body.kind,
                params=body.params,
                slug=body.slug,
                source_proposal=body.source_proposal,
            )
        except NotImplementedError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": path, "status": "draft"}

    @router.post("/actions/validate", dependencies=[Depends(canon_draft)])
    async def validate_action(body: ActionPathBody) -> dict[str, Any]:
        action = await state.canon_service._store.read_action(body.action_path)  # noqa: SLF001
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        result = await state.canon_service._validate(action)  # noqa: SLF001
        return {
            "status": result.status,
            "hard_blocks": list(result.hard_blocks),
        }

    @router.post("/actions/score", dependencies=[Depends(canon_draft)])
    async def score_action(body: ActionPathBody) -> dict[str, Any]:
        if state.canon_service._scorer is None:  # noqa: SLF001
            raise HTTPException(status_code=503, detail="scorer not wired")
        action = await state.canon_service._store.read_action(body.action_path)  # noqa: SLF001
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        score = await state.canon_service._scorer.score(action)  # noqa: SLF001
        return {
            "stability_score": score.stability_score,
            "risk_reasons": list(score.risk_reasons),
            "deterministic_evidence": list(score.deterministic_evidence),
            "model_evidence": list(score.model_evidence),
            "human_evidence": list(score.human_evidence),
            "scorer_version": score.scorer_version,
            "policy_profile_path": score.policy_profile_path,
        }

    # ---------------------------------------------------- apply / approve

    @router.post("/actions/apply", dependencies=[Depends(canon_apply)])
    async def apply_action(
        body: ActionPathBody,
        principal: Any = Depends(_principal),  # noqa: B008
    ) -> dict[str, Any]:
        result = await state.canon_service.apply_action(body.action_path, actor=_actor(principal))
        return {
            "action_path": result.action_path,
            "final_status": result.final_status,
            "affected_paths": list(result.affected_paths),
            "error": result.error,
        }

    @router.post("/actions/approve", dependencies=[Depends(canon_apply)])
    async def approve_action(
        body: ActionPathBody,
        principal: Any = Depends(_principal),  # noqa: B008
    ) -> dict[str, Any]:
        result = await state.canon_service.approve_action(body.action_path, actor=_actor(principal))
        return {
            "action_path": result.action_path,
            "final_status": result.final_status,
            "affected_paths": list(result.affected_paths),
        }

    @router.post("/actions/reject", dependencies=[Depends(canon_apply)])
    async def reject_action(
        body: RejectActionBody,
        principal: Any = Depends(_principal),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            await state.canon_service.reject_action(
                body.action_path, actor=_actor(principal), reason=body.reason
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"action_path": body.action_path, "final_status": "rejected"}

    @router.post("/stale/expire", dependencies=[Depends(canon_apply)])
    async def expire_stale(_body: ExpireBody | None = None) -> dict[str, Any]:
        # Slice 5 placeholder — `service.expire_stale` is implemented in
        # the watcher/cron plugin work (slice 6). For now this endpoint is
        # a no-op stub returning empty results so frontend/CI can wire it.
        return {"expired_proposals": [], "expired_actions": []}

    # ---------------------------------------------------- governance + policies

    @router.get("/policies/active", dependencies=[Depends(canon_read)])
    async def list_active_policies(kind: str | None = None) -> dict[str, Any]:
        policies = await state.canon_index.list_policies(status="active", kind=kind)
        return {"items": [_policy_to_dict(p) for p in policies]}

    return router


# ----------------------------------------------------------- helpers


def _actor(principal: Any) -> str:
    if principal is None:
        return "anonymous"
    return getattr(principal, "id", None) or getattr(principal, "name", None) or "user"


def _embedder_callable(state: AppState):
    """Return a callable suitable for ``BalancedProposer.embedder``.

    Skips embedding when the gateway-wired Embedder is disabled (no
    EMBEDDING_MODEL configured). The Tailscale Ollama URL (e.g.
    ``http://bsserver:11434``) is read from
    ``settings.embedding_api_base`` at gateway construction.
    """
    embedder = state.embedder
    if not embedder.enabled:
        return None

    async def _embed(ids: list[str]) -> list[list[float]]:
        return await embedder.embed_many(ids)

    return _embed


def _verifier_callable(state: AppState):
    """Return a callable suitable for ``BalancedProposer.verifier``.

    Wraps ``state.llm_client.chat`` with a short same-concept prompt and
    parses ``verdict`` + ``confidence`` from the JSON response. Returns
    None when no LLM model is configured.
    """
    if not state.settings.llm_model:
        return None

    import json as _json

    async def _verify(a: str, b: str) -> dict[str, Any]:
        prompt = (
            "You are a strict canonicalization judge. Decide whether two "
            "concept ids refer to the SAME underlying real-world concept "
            "(e.g. exact synonyms, abbreviation, alternate spelling) or "
            "DIFFERENT concepts. Return ONLY JSON: "
            '{"verdict": "same_concept" | "different_concept", '
            '"confidence": 0..1, "explanation": "<one sentence>"}.\n\n'
            f"A: {a}\nB: {b}"
        )
        try:
            raw = await state.llm_client.chat(
                system="", messages=[{"role": "user", "content": prompt}]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("canon_llm_verify_failed", a=a, b=b, error=str(exc))
            return {"verdict": "different_concept", "confidence": 0.5}
        # Be tolerant of stray text — find the first JSON object.
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            obj = _json.loads(raw[start:end])
        except (ValueError, _json.JSONDecodeError):
            logger.warning("canon_llm_verify_parse_failed", a=a, b=b, raw=raw[:200])
            return {"verdict": "different_concept", "confidence": 0.5}
        verdict = obj.get("verdict", "different_concept")
        if verdict not in {"same_concept", "different_concept"}:
            verdict = "different_concept"
        confidence = obj.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5
        return {
            "verdict": verdict,
            "confidence": confidence,
            "explanation": obj.get("explanation"),
        }

    return _verify
