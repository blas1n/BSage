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

from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from bsage.mcp.api import Tool, ToolContext, ToolRegistry

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas — first-class API contract for canon MCP tools.
# Output models intentionally allow ``extra`` so handler-supplied error
# envelopes (``{"error": "not_found", ...}``) round-trip cleanly through
# the dispatcher without bloating the typed surface.
# ---------------------------------------------------------------------------
class _PermissiveOutput(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- read tools ----------------------------------------------------------------
class ResolveTagInput(BaseModel):
    raw_tag: str
    raw_source: str | None = None
    auto_apply: bool = False


class ResolveTagOutput(_PermissiveOutput):
    raw_tag: str
    canonical: Any | None = None


class ListProposalsInput(BaseModel):
    status: str = "pending"
    kind: str | None = None


class _ProposalItem(_PermissiveOutput):
    path: str
    kind: str
    status: str
    score: float | None = None
    action_drafts: list[str] = Field(default_factory=list)


class ListProposalsOutput(_PermissiveOutput):
    items: list[_ProposalItem]


class GetProposalInput(BaseModel):
    path: str


class GetProposalOutput(_PermissiveOutput):
    """Read-tool output — covers both the success and ``not_found`` shape."""


class CreateActionDraftInput(BaseModel):
    kind: str
    params: dict[str, Any]
    slug: str | None = None
    source_proposal: str | None = None


class CreateActionDraftOutput(_PermissiveOutput):
    path: str
    status: str


class ActionPathInput(BaseModel):
    action_path: str


class ValidateActionOutput(_PermissiveOutput):
    """``{status, hard_blocks}`` on success / ``{error,...}`` on miss."""


class ScoreActionOutput(_PermissiveOutput):
    """Scorer envelope — wraps stability_score, risk_kinds, version, errors."""


class ApplyActionOutput(_PermissiveOutput):
    """Result envelope — action_path, final_status, affected_paths."""


class ListPoliciesInput(BaseModel):
    kind: str | None = None


class _PolicyItem(_PermissiveOutput):
    path: str
    kind: str
    profile_name: str
    priority: int


class ListPoliciesOutput(_PermissiveOutput):
    items: list[_PolicyItem]


# --- mutation tools -----------------------------------------------------------
class GenerateProposalsInput(BaseModel):
    strategy: Literal["deterministic", "balanced"] = "deterministic"
    threshold: float = 0.6


class GenerateProposalsOutput(_PermissiveOutput):
    strategy: str
    created: list[str]


class ExpireStaleInput(BaseModel):
    pass


class ExpireStaleOutput(_PermissiveOutput):
    expired_actions: list[str]
    expired_proposals: list[str]


class RejectActionInput(BaseModel):
    action_path: str
    reason: str | None = None


class RejectActionOutput(_PermissiveOutput):
    action_path: str
    final_status: str


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
            index_reader=getattr(state, "index_reader", None),
        )
    else:
        proposer = DeterministicProposer(
            index=state.canon_index,
            store=state.canon_service._store,  # noqa: SLF001
            threshold=threshold,
            index_reader=getattr(state, "index_reader", None),
        )
    paths = await proposer.generate()
    return {"strategy": strategy, "created": paths}


async def expire_stale(state: Any, args: dict[str, Any]) -> dict[str, Any]:
    result = await state.canon_service.expire_stale()
    return {
        "expired_actions": list(result.expired_actions),
        "expired_proposals": list(result.expired_proposals),
    }


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


# ---------------------------------------------------------------------------
# First-class :class:`Tool` registration. Handlers thinly wrap the
# existing ``(state, args)`` dispatchers above so we never rebuild the
# canonicalization service contract — only the wire schema and the
# audit/scope plumbing live here.
# ---------------------------------------------------------------------------
def _wrap(fn: Any) -> Any:
    """Adapt a legacy ``(state, dict) -> dict`` canon dispatcher to the
    first-class ``(BaseModel, ToolContext) -> dict`` handler signature.
    """

    async def _handler(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
        return await fn(ctx.state, args.model_dump())

    return _handler


_CANON_READ_TOOLS: list[Tool] = [
    Tool(
        name="canonicalization_resolve_tag",
        description=(
            "Resolve a raw tag against the concept registry. Returns "
            "{canonical, status} where status is one of resolved / "
            "new_candidate / pending_candidate / ambiguous / blocked."
        ),
        input_schema=ResolveTagInput,
        output_schema=ResolveTagOutput,
        handler=_wrap(resolve_tag),
    ),
    Tool(
        name="canonicalization_list_proposals",
        description=(
            "List proposal notes by status/kind. Output: list of "
            "{path, kind, status, score, action_drafts}. Read full "
            "evidence via get_note."
        ),
        input_schema=ListProposalsInput,
        output_schema=ListProposalsOutput,
        handler=_wrap(list_proposals),
    ),
    Tool(
        name="canonicalization_get_proposal",
        description=(
            "Read a single proposal note as a structured summary "
            "(score, evidence kinds, linked action drafts). For full "
            "markdown body, use get_note."
        ),
        input_schema=GetProposalInput,
        output_schema=GetProposalOutput,
        handler=_wrap(get_proposal),
    ),
    Tool(
        name="canonicalization_create_action_draft",
        description=(
            "Create a typed action draft. Apply requires a separate "
            "canonicalization_apply_action call. Supported kinds: "
            "create-concept, retag-notes, merge-concepts, create-decision."
        ),
        input_schema=CreateActionDraftInput,
        output_schema=CreateActionDraftOutput,
        handler=_wrap(create_action_draft),
        audit_event="bsage.mcp.canon.action_draft.created",
    ),
    Tool(
        name="canonicalization_validate_action",
        description=(
            "Run deterministic validation on an action draft. Returns "
            "{status, hard_blocks: list of envelope-shaped reasons}."
        ),
        input_schema=ActionPathInput,
        output_schema=ValidateActionOutput,
        handler=_wrap(validate_action),
    ),
    Tool(
        name="canonicalization_score_action",
        description=(
            "Compute scoring + envelope-shaped risk_reasons for an "
            "action. Source separation: deterministic vs model vs human."
        ),
        input_schema=ActionPathInput,
        output_schema=ScoreActionOutput,
        handler=_wrap(score_action),
    ),
    Tool(
        name="canonicalization_apply_action",
        description=(
            "Apply a typed action. Honors Safe Mode — when ON without "
            "interface available, returns final_status=pending_approval "
            "and no domain mutations occur."
        ),
        input_schema=ActionPathInput,
        output_schema=ApplyActionOutput,
        handler=_wrap(apply_action),
        audit_event="bsage.mcp.canon.action.applied",
    ),
    Tool(
        name="canonicalization_list_policies",
        description=("List active policy profiles ({path, kind, profile_name, priority, params})."),
        input_schema=ListPoliciesInput,
        output_schema=ListPoliciesOutput,
        handler=_wrap(list_policies),
    ),
]


_CANON_OPTIONAL_TOOLS: list[Tool] = [
    Tool(
        name="canonicalization_generate_proposals",
        description=(
            "Run the proposal generator (deterministic | balanced) and "
            "return the list of created proposal paths. Cost-gated — "
            "balanced consumes embedding/LLM credits."
        ),
        input_schema=GenerateProposalsInput,
        output_schema=GenerateProposalsOutput,
        handler=_wrap(generate_proposals),
        audit_event="bsage.mcp.canon.proposals.generated",
    ),
    Tool(
        name="canonicalization_expire_stale",
        description=("Mark stale draft/proposal notes as expired (slice 6 plugin)."),
        input_schema=ExpireStaleInput,
        output_schema=ExpireStaleOutput,
        handler=_wrap(expire_stale),
        audit_event="bsage.mcp.canon.stale.expired",
    ),
    Tool(
        name="canonicalization_approve_action",
        description=(
            "Approve a pending_approval action. Disabled by default — "
            "MCP clients are not approval actors unless explicitly "
            "trusted."
        ),
        input_schema=ActionPathInput,
        output_schema=ApplyActionOutput,
        handler=_wrap(approve_action),
        audit_event="bsage.mcp.canon.action.approved",
    ),
    Tool(
        name="canonicalization_reject_action",
        description="Reject a pending_approval action with optional reason.",
        input_schema=RejectActionInput,
        output_schema=RejectActionOutput,
        handler=_wrap(reject_action),
        audit_event="bsage.mcp.canon.action.rejected",
    ),
]


def register_canon_tools(
    registry: ToolRegistry,
    *,
    mutation_enabled: bool,
) -> None:
    """Register canonicalization tools as first-class MCP tools.

    Always registers the eight read tools. The four mutation tools are
    only registered when ``mutation_enabled=True`` — preserving the
    Handoff §15.2 contract that MCP approval/mutation tools default OFF.
    """
    for tool in _CANON_READ_TOOLS:
        registry.register(tool)
    if mutation_enabled:
        for tool in _CANON_OPTIONAL_TOOLS:
            registry.register(tool)


def canon_tool_names(*, mutation_enabled: bool) -> list[str]:
    """Names of canon tools that would be registered for the given gate."""
    names = [t.name for t in _CANON_READ_TOOLS]
    if mutation_enabled:
        names.extend(t.name for t in _CANON_OPTIONAL_TOOLS)
    return names
