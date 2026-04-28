"""Seed refinement helper used by :class:`bsage.core.agent_loop.AgentLoop`.

Split out of the original ``agent_loop.py`` (M15, Hardening Sprint 2) so the
refinement logic — fallback prompt + lightweight LLM JSON parse — can be
exercised in isolation without instantiating the full :class:`AgentLoop`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.prompt_registry import PromptRegistry
    from bsage.core.skill_context import LLMClient

logger = structlog.get_logger(__name__)

REFINE_PROMPT_FALLBACK = (
    "You are a data cleaner for a personal knowledge base. "
    "Clean the following input WITHOUT changing its meaning.\n"
    "Rules:\n"
    "- Fix typos and grammar\n"
    "- Extract the core content (remove noise, repetition)\n"
    "- Generate a concise title (under 30 chars)\n"
    "- Assign up to 3 relevant tags\n"
    '- Output ONLY valid JSON: {"title": "...", "content": "...", "tags": [...]}\n'
    "- Preserve the original language (Korean, English, etc.)"
)
"""Inline fallback prompt used when no :class:`PromptRegistry` is wired in."""


def resolve_refine_prompt(prompt_registry: PromptRegistry | None) -> str:
    """Return the seed-refiner prompt from the registry or the inline fallback.

    Pure function — easy to unit-test against a mocked registry.
    """
    if prompt_registry is not None:
        try:
            return prompt_registry.get("seed-refiner")
        except KeyError:
            pass
    return REFINE_PROMPT_FALLBACK


async def refine_seed(
    *,
    plugin_name: str,
    raw_data: dict[str, Any],
    llm_client: LLMClient,
    prompt_registry: PromptRegistry | None,
) -> dict[str, Any]:
    """Refine raw input data using a lightweight LLM pass.

    Falls back to ``raw_data`` unchanged when:

    * ``raw_data`` is already structured (has ``title`` and ``content`` keys),
    * ``raw_data`` serialises to fewer than 20 characters of JSON, or
    * the LLM call/parsing fails for any expected error.

    The function never raises — refinement is best-effort and must never
    break ingestion (see also Sprint 1 PR #24).
    """
    # If already structured (has title + content), skip refinement
    if "title" in raw_data and "content" in raw_data:
        return raw_data

    raw_text = json.dumps(raw_data, default=str, ensure_ascii=False)
    if len(raw_text) < 20:
        return raw_data

    response = ""
    try:
        response = await llm_client.chat(
            system=resolve_refine_prompt(prompt_registry),
            messages=[{"role": "user", "content": raw_text}],
        )
        parsed = json.loads(response.strip())
        if isinstance(parsed, dict) and "title" in parsed and "content" in parsed:
            logger.info("seed_refined", plugin_name=plugin_name)
            return parsed
    except Exception:
        logger.debug(
            "seed_refine_failed_using_raw",
            plugin_name=plugin_name,
            response_preview=response[:200],
            exc_info=True,
        )

    return raw_data


__all__ = ["REFINE_PROMPT_FALLBACK", "refine_seed", "resolve_refine_prompt"]
