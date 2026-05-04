"""IngestCompiler — compile knowledge at ingestion time, not query time.

Inspired by Karpathy Wiki: when new data arrives, immediately find and
update/create related garden notes instead of waiting for scheduled skills.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog

from bsage.core.events import emit_event
from bsage.garden.writer import GardenNote

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.core.skill_context import LLMClient
    from bsage.garden.retriever import VaultRetriever
    from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)

# Conservative fallback when nothing better is known about the model
# (no probe, no override). Tuned for small local LLMs — large frontier
# models will set their own budget via :func:`derive_batch_char_budget`
# at AppState construction time. Single items larger than the budget
# are truncated rather than allowed to balloon the prompt.
_DEFAULT_BATCH_CHAR_BUDGET = 5_000

COMPILE_BATCH_SYSTEM_PROMPT = """\
You are an ingest compiler for a personal knowledge base (Obsidian vault).

You are given a BATCH of NEW seeds (numbered) plus EXISTING notes from the \
vault. Produce a SINGLE consolidated plan that covers the entire batch.

## Rules
- Treat the whole batch as one body of incoming material — deduplicate \
across seeds, merge related items into one garden note when reasonable, \
and only create separate notes when the topics are genuinely distinct.
- Prefer updating existing notes over creating new ones.
- Each action must have a clear reason that names which seed numbers it \
covers (e.g. "consolidates seeds #1, #4, #7").
- Return a JSON array of actions. Each action object has these fields:
  - "action": "create" | "update" | "append"
  - "target_path": vault-relative path (required for update/append, null for create)
  - "title": note title
  - "content": markdown content (full body for create/update, section to append)
  - "note_type": one of idea, insight, project, event, task, fact, person, preference
  - "reason": why this action is needed (cite seed numbers)
  - "related": list of related note titles for cross-linking
  - "source_seeds": list of seed numbers this action draws from

Return ONLY the JSON array, no other text.
If no actions are needed, return an empty array: []
"""


@dataclass
class UpdateAction:
    """A single update/create/append action planned by the LLM."""

    action: Literal["update", "append", "create"]
    target_path: str | None
    title: str
    content: str
    note_type: str
    reason: str
    related: list[str] = field(default_factory=list)


@dataclass
class CompileResult:
    """Result of an ingest compilation."""

    actions_taken: list[UpdateAction]
    notes_updated: int
    notes_created: int
    seed_path: str = ""
    llm_calls: int = 1


@dataclass
class BatchItem:
    """One labelled chunk fed to :meth:`IngestCompiler.compile_batch`.

    ``label`` is a human-readable identifier (e.g. filename) so the LLM
    can reference seeds in its reasoning. ``content`` is the raw seed
    text the LLM should consider.
    """

    label: str
    content: str


_REQUIRED_ACTION_FIELDS = {"action", "title", "content", "note_type", "reason"}


def _empty_compile_result() -> CompileResult:
    return CompileResult(actions_taken=[], notes_updated=0, notes_created=0)


class IngestCompiler:
    """Compile seed content into garden notes at ingestion time."""

    def __init__(
        self,
        garden_writer: GardenWriter,
        llm_client: LLMClient,
        retriever: VaultRetriever | None = None,
        event_bus: EventBus | None = None,
        max_updates: int = 10,
        batch_char_budget: int | None = None,
    ) -> None:
        self._writer = garden_writer
        self._llm = llm_client
        self._retriever = retriever
        self._event_bus = event_bus
        self._max_updates = max_updates
        # ``None`` → conservative default; callers that know the model
        # (AppState construction) should pass a probed value.
        self._batch_char_budget = batch_char_budget or _DEFAULT_BATCH_CHAR_BUDGET

    async def compile_batch(
        self,
        items: list[BatchItem],
        seed_source: str,
    ) -> CompileResult:
        """Compile multiple seeds with a single LLM plan.

        Plugins that import N files (ai-memory-input ZIP, chatgpt
        conversation export, etc.) call this once per import — the LLM
        sees every seed at once and produces a consolidated plan that
        can deduplicate, merge, and cross-reference across the batch.
        Cuts a 30-call import down to one (or a small number of
        chunks when the combined text exceeds ``_BATCH_CHAR_BUDGET``).
        """
        if not items:
            return _empty_compile_result()

        await emit_event(
            self._event_bus,
            "INGEST_COMPILE_BATCH_START",
            {"source": seed_source, "item_count": len(items)},
        )

        chunks = _chunk_batch(items, self._batch_char_budget)
        actions_taken: list[UpdateAction] = []
        notes_created = 0
        notes_updated = 0
        llm_calls = 0

        try:
            for chunk in chunks:
                # Per-chunk related lookup — each chunk gets vault context
                # relevant to ITS own seeds, not items 1-3 of the whole
                # batch. Lets the LLM reuse / update existing notes
                # instead of always creating new ones.
                chunk_query = "\n\n".join(item.content[:500] for item in chunk)
                related_context = await self._find_related(chunk_query)

                plan = await self._plan_batch_updates(chunk, seed_source, related_context)
                llm_calls += 1
                chunk_result = await self._execute_plan(plan)
                actions_taken.extend(chunk_result.actions_taken)
                notes_created += chunk_result.notes_created
                notes_updated += chunk_result.notes_updated
        except Exception:
            logger.warning(
                "ingest_compile_batch_failed_using_noop",
                source=seed_source,
                item_count=len(items),
                exc_info=True,
            )
            return _empty_compile_result()

        await emit_event(
            self._event_bus,
            "INGEST_COMPILE_BATCH_COMPLETE",
            {
                "source": seed_source,
                "item_count": len(items),
                "llm_calls": llm_calls,
                "notes_updated": notes_updated,
                "notes_created": notes_created,
            },
        )

        logger.info(
            "ingest_compile_batch_complete",
            source=seed_source,
            items=len(items),
            llm_calls=llm_calls,
            updated=notes_updated,
            created=notes_created,
        )
        return CompileResult(
            actions_taken=actions_taken,
            notes_updated=notes_updated,
            notes_created=notes_created,
            llm_calls=llm_calls,
        )

    async def _find_related(self, seed_content: str) -> str:
        """Search vault for notes related to seed content."""
        if self._retriever is None:
            return "No existing notes available."
        return await self._retriever.search(query=seed_content)

    async def _plan_batch_updates(
        self,
        items: list[BatchItem],
        seed_source: str,
        related_context: str,
    ) -> list[dict[str, Any]]:
        """Ask the LLM to plan updates covering an entire batch in one call."""
        seed_blocks = []
        for idx, item in enumerate(items, start=1):
            seed_blocks.append(f"### Seed #{idx} — {item.label}\n\n{item.content.strip()}\n")
        seeds_text = "\n".join(seed_blocks)
        user_msg = (
            f"## New Seeds (source: {seed_source}, count: {len(items)})\n\n"
            f"{seeds_text}\n\n"
            f"## Existing Related Notes\n\n{related_context}"
        )
        raw = await self._llm.chat(
            system=COMPILE_BATCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        return self._parse_plan(raw)

    def _parse_plan(self, raw: str) -> list[dict[str, Any]]:
        """Parse LLM response as JSON array of actions."""
        text = raw.strip()
        # Try to extract JSON array if wrapped in markdown code block
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                text = text[start : end + 1]
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("ingest_compile_parse_failed", raw=text[:200])
            return []
        if not isinstance(parsed, list):
            return []
        return parsed

    async def _execute_plan(self, plan: list[dict[str, Any]]) -> CompileResult:
        """Execute the planned actions, capped by max_updates."""
        actions_taken: list[UpdateAction] = []
        notes_created = 0
        notes_updated = 0

        for raw_action in plan[: self._max_updates]:
            if not self._validate_action(raw_action):
                continue

            action = UpdateAction(
                action=raw_action["action"],
                target_path=raw_action.get("target_path"),
                title=raw_action["title"],
                content=raw_action["content"],
                note_type=raw_action["note_type"],
                reason=raw_action["reason"],
                related=raw_action.get("related", []),
            )

            try:
                if action.action == "create":
                    await self._writer.write_garden(
                        GardenNote(
                            title=action.title,
                            content=action.content,
                            note_type=action.note_type,
                            source="ingest-compiler",
                            related=action.related,
                        )
                    )
                    notes_created += 1
                elif action.action == "update" and action.target_path:
                    await self._writer.update_note(action.target_path, action.content)
                    notes_updated += 1
                elif action.action == "append" and action.target_path:
                    await self._writer.append_to_note(action.target_path, action.content)
                    notes_updated += 1
                else:
                    logger.warning("ingest_compile_invalid_action", action=action.action)
                    continue
            except (FileNotFoundError, ValueError, OSError) as exc:
                logger.warning(
                    "ingest_compile_action_failed",
                    action=action.action,
                    title=action.title,
                    error=str(exc),
                )
                continue

            actions_taken.append(action)

        return CompileResult(
            actions_taken=actions_taken,
            notes_updated=notes_updated,
            notes_created=notes_created,
        )

    def _validate_action(self, raw: dict[str, Any]) -> bool:
        """Check that raw action dict has all required fields."""
        if not isinstance(raw, dict):
            return False
        missing = _REQUIRED_ACTION_FIELDS - raw.keys()
        if missing:
            logger.debug("ingest_compile_action_missing_fields", missing=list(missing))
            return False
        if raw["action"] not in ("create", "update", "append"):
            return False
        return not (raw["action"] in ("update", "append") and not raw.get("target_path"))


def _chunk_batch(items: list[BatchItem], char_budget: int) -> list[list[BatchItem]]:
    """Split items into chunks whose total content stays under char_budget.

    Items larger than the budget are truncated (with a marker) so a
    single mega-file (e.g. an index page) can't blow up the prompt and
    starve the LLM. Order is preserved so seed numbering stays
    meaningful within each chunk.
    """
    chunks: list[list[BatchItem]] = []
    current: list[BatchItem] = []
    current_size = 0
    for raw_item in items:
        item = _truncate_item(raw_item, char_budget)
        item_size = len(item.content)
        if current and current_size + item_size > char_budget:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += item_size
    if current:
        chunks.append(current)
    return chunks


def _truncate_item(item: BatchItem, max_chars: int) -> BatchItem:
    """Cap an oversized item's content so it can fit in a single chunk."""
    if len(item.content) <= max_chars:
        return item
    head = item.content[: max_chars - 80]
    return BatchItem(
        label=item.label,
        content=f"{head}\n\n…[truncated for batch budget; original was {len(item.content)} chars]…",
    )


# Reserve this fraction of the model's input window for the system
# prompt, the per-batch frame text, and headroom for the JSON output —
# the rest gets allocated to seed payload.
_BUDGET_SAFETY_FRACTION = 0.4

# Rough chars-per-token for ASCII-heavy markdown. Korean/CJK runs ~2,
# but we're erring conservative on input length, not output.
_CHARS_PER_TOKEN = 3.5

# Local ollama models often DECLARE huge context windows (200k+) but
# actually generate slowly past a few thousand chars of input.
# Empirically, glm-4.7-flash on consumer GPU times out (>300s) at
# 16k input; 5-8k is the practical sweet spot. Cap their derived
# budget here — doesn't apply to hosted models (anthropic/openai/etc.)
# which handle long prompts efficiently.
_OLLAMA_BUDGET_CAP = 8_000


async def derive_batch_char_budget(
    model: str,
    api_base: str | None = None,
    *,
    fallback: int = _DEFAULT_BATCH_CHAR_BUDGET,
) -> int:
    """Probe the configured model for its context window, return a safe budget.

    Looks up the input-token limit (ollama via ``/api/show``, others via
    litellm's static model registry) and converts to a char budget that
    keeps room for the system prompt + LLM output. Falls back to
    ``fallback`` if probing fails.

    Computed once at AppState construction time and passed into
    :class:`IngestCompiler` — runtime model swaps trigger a re-probe at
    the same boundary.
    """
    max_input_tokens = await _probe_max_input_tokens(model, api_base)
    if max_input_tokens is None:
        logger.info("ingest_batch_budget_fallback", model=model, chars=fallback)
        return fallback
    budget = int(max_input_tokens * _CHARS_PER_TOKEN * _BUDGET_SAFETY_FRACTION)
    # Don't go below the conservative default — micro-models would just
    # produce thrashing chunks otherwise.
    budget = max(budget, _DEFAULT_BATCH_CHAR_BUDGET)
    # Local ollama models advertise huge contexts but generate slowly
    # past a few thousand input chars. Cap them so we don't ship a
    # technically-correct-but-practically-broken single 200k char
    # prompt to a small local model.
    if model.startswith(("ollama/", "ollama_chat/")):
        budget = min(budget, _OLLAMA_BUDGET_CAP)
    logger.info(
        "ingest_batch_budget_derived",
        model=model,
        max_input_tokens=max_input_tokens,
        chars=budget,
    )
    return budget


async def _probe_max_input_tokens(model: str, api_base: str | None) -> int | None:
    """Return max input tokens for the model, or ``None`` if unknown."""
    if model.startswith(("ollama/", "ollama_chat/")) and api_base:
        return await _ollama_context_length(model, api_base)
    return _litellm_max_input_tokens(model)


async def _ollama_context_length(model: str, api_base: str) -> int | None:
    """Ask ollama's ``/api/show`` for the model's declared context length."""
    bare_name = model.split("/", 1)[1] if "/" in model else model
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{api_base.rstrip('/')}/api/show", json={"name": bare_name})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    info = data.get("model_info") or {}
    # ollama returns architecture-keyed entries like "glm.context_length".
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


def _litellm_max_input_tokens(model: str) -> int | None:
    """Look up the model in litellm's static registry."""
    try:
        import litellm

        info = litellm.get_model_info(model)
    except Exception:
        return None
    raw = info.get("max_input_tokens") if isinstance(info, dict) else None
    return raw if isinstance(raw, int) and raw > 0 else None
