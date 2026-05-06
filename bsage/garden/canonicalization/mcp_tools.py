"""MCP tool dispatchers for canonicalization (Handoff §15.2).

Tools share their core implementation with the REST routes — they call
the same ``CanonicalizationService`` methods. Output is concise and
path-oriented per spec; full evidence is retrieved via ``get_note``.

Static (always exposed) tools:
- canonicalization_resolve_tag
- canonicalization_list_proposals
- canonicalization_get_proposal
- canonicalization_create_action_draft
- canonicalization_validate_action
- canonicalization_score_action
- canonicalization_apply_action
- canonicalization_list_policies

Optional (authz/cost-gated, off by default):
- canonicalization_generate_proposals
- canonicalization_expire_stale
- canonicalization_approve_action
- canonicalization_reject_action

Per §15.2 — MCP MUST NOT expose generic frontmatter editing for
canonicalization resources. Mutation goes through typed action tools.
Read-only deployment is a valid mode (set
``settings.mcp_canon_mutation_enabled = False`` to disable mutators).
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


CANON_TOOL_DEFS: list[dict[str, Any]] = [
    # ----------------------------------------- read tools (static, always)
    {
        "name": "canonicalization_resolve_tag",
        "description": (
            "Resolve a raw tag against the concept registry. Returns "
            "{canonical, status} where status is one of resolved / "
            "new_candidate / pending_candidate / ambiguous / blocked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_tag": {"type": "string"},
                "raw_source": {"type": "string"},
                "auto_apply": {"type": "boolean", "default": False},
            },
            "required": ["raw_tag"],
        },
    },
    {
        "name": "canonicalization_list_proposals",
        "description": (
            "List proposal notes by status/kind. Output: list of "
            "{path, kind, status, score, action_drafts}. Read full "
            "evidence via get_note."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "pending"},
                "kind": {"type": "string"},
            },
        },
    },
    {
        "name": "canonicalization_get_proposal",
        "description": (
            "Read a single proposal note as a structured summary "
            "(score, evidence kinds, linked action drafts). For full "
            "markdown body, use get_note."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "canonicalization_create_action_draft",
        "description": (
            "Create a typed action draft. Apply requires a separate "
            "canonicalization_apply_action call. Supported kinds: "
            "create-concept, retag-notes, merge-concepts, create-decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "params": {"type": "object", "additionalProperties": True},
                "slug": {"type": "string"},
                "source_proposal": {"type": "string"},
            },
            "required": ["kind", "params"],
        },
    },
    {
        "name": "canonicalization_validate_action",
        "description": (
            "Run deterministic validation on an action draft. Returns "
            "{status, hard_blocks: list of envelope-shaped reasons}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"action_path": {"type": "string"}},
            "required": ["action_path"],
        },
    },
    {
        "name": "canonicalization_score_action",
        "description": (
            "Compute scoring + envelope-shaped risk_reasons for an action. "
            "Source separation: deterministic vs model vs human."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"action_path": {"type": "string"}},
            "required": ["action_path"],
        },
    },
    {
        "name": "canonicalization_apply_action",
        "description": (
            "Apply a typed action. Honors Safe Mode — when ON without "
            "interface available, returns final_status=pending_approval "
            "and no domain mutations occur."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"action_path": {"type": "string"}},
            "required": ["action_path"],
        },
    },
    {
        "name": "canonicalization_list_policies",
        "description": (
            "List active policy profiles ({path, kind, profile_name, priority, params})."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"kind": {"type": "string"}},
        },
    },
]

# Optional tools — wired only when settings.mcp_canon_mutation_enabled is True.
CANON_OPTIONAL_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "canonicalization_generate_proposals",
        "description": (
            "Run the proposal generator (deterministic | balanced) and "
            "return the list of created proposal paths. Cost-gated — "
            "balanced consumes embedding/LLM credits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["deterministic", "balanced"],
                    "default": "deterministic",
                },
                "threshold": {"type": "number", "default": 0.6},
            },
        },
    },
    {
        "name": "canonicalization_expire_stale",
        "description": "Mark stale draft/proposal notes as expired (slice 6 plugin).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "canonicalization_approve_action",
        "description": (
            "Approve a pending_approval action. Disabled by default — "
            "MCP clients are not approval actors unless explicitly trusted."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"action_path": {"type": "string"}},
            "required": ["action_path"],
        },
    },
    {
        "name": "canonicalization_reject_action",
        "description": "Reject a pending_approval action with optional reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_path": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["action_path"],
        },
    },
]


# -------------------------------------------------------------- dispatchers


async def resolve_tag(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    canonical = await state.canon_service.resolve_and_canonicalize(
        args["raw_tag"],
        raw_source=args.get("raw_source"),
        auto_apply=bool(args.get("auto_apply", False)),
    )
    return {"raw_tag": args["raw_tag"], "canonical": canonical}


async def list_proposals(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    proposals = await state.canon_index.list_proposals(
        status=args.get("status", "pending"), kind=args.get("kind")
    )
    return {
        "items": [
            {
                "path": p.path,
                "kind": p.kind,
                "status": p.status,
                "score": p.proposal_score,
                "action_drafts": list(p.action_drafts),
            }
            for p in proposals
        ]
    }


async def get_proposal(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    p = await state.canon_service._store.read_proposal(args["path"])  # noqa: SLF001
    if p is None:
        return {"error": "not_found", "path": args["path"]}
    return {
        "path": p.path,
        "kind": p.kind,
        "status": p.status,
        "strategy": p.strategy,
        "score": p.proposal_score,
        "evidence_kinds": [e.get("kind") for e in p.evidence],
        "action_drafts": list(p.action_drafts),
        "result_actions": list(p.result_actions),
    }


async def create_action_draft(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    path = await state.canon_service.create_action_draft(
        kind=args["kind"],
        params=args["params"],
        slug=args.get("slug"),
        source_proposal=args.get("source_proposal"),
    )
    return {"path": path, "status": "draft"}


async def validate_action(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    action = await state.canon_service._store.read_action(args["action_path"])  # noqa: SLF001
    if action is None:
        return {"error": "not_found", "action_path": args["action_path"]}
    result = await state.canon_service._validate(action)  # noqa: SLF001
    return {
        "status": result.status,
        "hard_blocks": [
            {"kind": b.get("kind"), "reason": b.get("payload", {}).get("reason")}
            for b in result.hard_blocks
        ],
    }


async def score_action(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    if state.canon_service._scorer is None:  # noqa: SLF001
        return {"error": "scorer_not_wired"}
    action = await state.canon_service._store.read_action(args["action_path"])  # noqa: SLF001
    if action is None:
        return {"error": "not_found", "action_path": args["action_path"]}
    score = await state.canon_service._scorer.score(action)  # noqa: SLF001
    return {
        "stability_score": score.stability_score,
        "risk_kinds": [r.get("kind") for r in score.risk_reasons],
        "scorer_version": score.scorer_version,
    }


async def apply_action(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    result = await state.canon_service.apply_action(args["action_path"], actor="mcp")
    return {
        "action_path": result.action_path,
        "final_status": result.final_status,
        "affected_paths": list(result.affected_paths),
    }


async def list_policies(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    policies = await state.canon_index.list_policies(status="active", kind=args.get("kind"))
    return {
        "items": [
            {
                "path": p.path,
                "kind": p.kind,
                "profile_name": p.profile_name,
                "priority": p.priority,
            }
            for p in policies
        ]
    }


async def generate_proposals(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    from bsage.garden.canonicalization.proposals import (
        BalancedProposer,
        DeterministicProposer,
    )

    strategy = args.get("strategy", "deterministic")
    threshold = float(args.get("threshold", 0.6))
    if strategy == "balanced":
        from bsage.gateway.canonicalization_routes import (
            _embedder_callable,
            _verifier_callable,
        )

        proposer = BalancedProposer(
            index=state.canon_index,
            store=state.canon_service._store,  # noqa: SLF001
            threshold=threshold,
            decisions=state.canon_decisions,
            embedder=_embedder_callable(state),
            verifier=_verifier_callable(state),
        )
    else:
        proposer = DeterministicProposer(
            index=state.canon_index,
            store=state.canon_service._store,  # noqa: SLF001
            threshold=threshold,
        )
    paths = await proposer.generate()
    return {"strategy": strategy, "created": paths}


async def expire_stale(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    # Slice 5 placeholder — see comment in REST stale/expire handler.
    return {"expired_proposals": [], "expired_actions": []}


async def approve_action(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    result = await state.canon_service.approve_action(args["action_path"], actor="mcp")
    return {
        "action_path": result.action_path,
        "final_status": result.final_status,
        "affected_paths": list(result.affected_paths),
    }


async def reject_action(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    await state.canon_service.reject_action(
        args["action_path"], actor="mcp", reason=args.get("reason")
    )
    return {"action_path": args["action_path"], "final_status": "rejected"}


CANON_DISPATCH = {
    "canonicalization_resolve_tag": resolve_tag,
    "canonicalization_list_proposals": list_proposals,
    "canonicalization_get_proposal": get_proposal,
    "canonicalization_create_action_draft": create_action_draft,
    "canonicalization_validate_action": validate_action,
    "canonicalization_score_action": score_action,
    "canonicalization_apply_action": apply_action,
    "canonicalization_list_policies": list_policies,
}

CANON_OPTIONAL_DISPATCH = {
    "canonicalization_generate_proposals": generate_proposals,
    "canonicalization_expire_stale": expire_stale,
    "canonicalization_approve_action": approve_action,
    "canonicalization_reject_action": reject_action,
}
