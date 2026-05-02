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

COMPILE_SYSTEM_PROMPT = """\
You are an ingest compiler for a personal knowledge base (Obsidian vault).

Given NEW seed content and EXISTING notes from the vault, decide which notes \
to update and which new notes to create.

## Rules
- Only create/update notes when the seed contains genuinely useful information.
- Prefer updating existing notes over creating new ones (avoid duplication).
- Each action must have a clear reason.
- Return a JSON array of actions. Each action object has these fields:
  - "action": "create" | "update" | "append"
  - "target_path": vault-relative path (required for update/append, null for create)
  - "title": note title
  - "content": markdown content (full body for create/update, section to append)
  - "note_type": one of idea, insight, project, event, task, fact, person, preference
  - "reason": why this action is needed
  - "related": list of related note titles for cross-linking

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
    ) -> None:
        self._writer = garden_writer
        self._llm = llm_client
        self._retriever = retriever
        self._event_bus = event_bus
        self._max_updates = max_updates

    async def compile(self, seed_content: str, seed_source: str) -> CompileResult:
        """Compile seed into garden note updates/creations.

        Args:
            seed_content: The seed text to compile.
            seed_source: Source plugin name.

        Returns:
            CompileResult with actions taken and counts.
        """
        await emit_event(
            self._event_bus,
            "INGEST_COMPILE_START",
            {"source": seed_source},
        )

        try:
            # 1. Search for related existing notes
            related_context = await self._find_related(seed_content)

            # 2. Ask LLM to plan updates
            plan = await self._plan_updates(seed_content, seed_source, related_context)

            # 3. Execute the plan
            result = await self._execute_plan(plan)
        except Exception:
            logger.warning(
                "ingest_compile_failed_using_noop",
                source=seed_source,
                exc_info=True,
            )
            result = _empty_compile_result()

        await emit_event(
            self._event_bus,
            "INGEST_COMPILE_COMPLETE",
            {
                "source": seed_source,
                "notes_updated": result.notes_updated,
                "notes_created": result.notes_created,
            },
        )

        logger.info(
            "ingest_compile_complete",
            source=seed_source,
            updated=result.notes_updated,
            created=result.notes_created,
        )
        return result

    async def _find_related(self, seed_content: str) -> str:
        """Search vault for notes related to seed content."""
        if self._retriever is None:
            return "No existing notes available."
        return await self._retriever.search(query=seed_content)

    async def _plan_updates(
        self, seed_content: str, seed_source: str, related_context: str
    ) -> list[dict[str, Any]]:
        """Ask LLM to plan which notes to create/update."""
        user_msg = (
            f"## New Seed (source: {seed_source})\n\n{seed_content}\n\n"
            f"## Existing Related Notes\n\n{related_context}"
        )
        raw = await self._llm.chat(
            system=COMPILE_SYSTEM_PROMPT,
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
