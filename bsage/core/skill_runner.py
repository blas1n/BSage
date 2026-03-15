"""SkillRunner — executes LLM-based Skills (GATHER → LLM → APPLY pipeline)."""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from typing import TYPE_CHECKING

import structlog

from bsage.core.events import emit_event
from bsage.core.exceptions import SkillRunError
from bsage.core.skill_loader import OutputTarget
from bsage.garden.vault import VaultPathError

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.core.prompt_registry import PromptRegistry
    from bsage.core.skill_context import SkillContext
    from bsage.core.skill_loader import SkillMeta
    from bsage.garden.retriever import VaultRetriever

# Maximum number of notes to read per vault subdirectory during GATHER phase.
_MAX_NOTES_PER_DIR = 20
# Maximum total characters of vault context to feed into the LLM prompt.
_MAX_CONTEXT_CHARS = 50_000

logger = structlog.get_logger(__name__)

_BACKTICK_FENCE_RE = re.compile(r"```+(?:\s*json)?\s*\n(.*?)```+", re.DOTALL | re.IGNORECASE)
_TILDE_FENCE_RE = re.compile(r"~~~+(?:\s*json)?\s*\n(.*?)~~~+", re.DOTALL | re.IGNORECASE)


def _strip_json_fence(text: str) -> str:
    """Remove markdown code fences around JSON content."""
    match = _BACKTICK_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    match = _TILDE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


class SkillRunner:
    """Executes LLM-based Skills via the GATHER → LLM → APPLY pipeline."""

    def __init__(
        self,
        prompt_registry: PromptRegistry | None = None,
        event_bus: EventBus | None = None,
        retriever: VaultRetriever | None = None,
    ) -> None:
        self._prompt_registry = prompt_registry
        self._event_bus = event_bus
        self._retriever = retriever

    async def run(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Execute a Skill via the 3-phase LLM pipeline and return the result dict.

        Raises:
            SkillRunError: On execution failure.
        """
        logger.info("skill_run_start", name=skill_meta.name, category=skill_meta.category)
        correlation_id = str(uuid.uuid4())

        await emit_event(
            self._event_bus,
            "SKILL_RUN_START",
            {"name": skill_meta.name, "category": skill_meta.category},
            correlation_id=correlation_id,
        )

        try:
            result = await self._run_llm(skill_meta, context, correlation_id)
        except SkillRunError:
            await emit_event(
                self._event_bus,
                "SKILL_RUN_ERROR",
                {"name": skill_meta.name, "error": "execution failed"},
                correlation_id=correlation_id,
            )
            raise
        except Exception as exc:
            await emit_event(
                self._event_bus,
                "SKILL_RUN_ERROR",
                {"name": skill_meta.name, "error": str(exc)},
                correlation_id=correlation_id,
            )
            raise SkillRunError(f"Skill '{skill_meta.name}' execution failed: {exc}") from exc

        logger.info("skill_run_complete", name=skill_meta.name)
        await emit_event(
            self._event_bus,
            "SKILL_RUN_COMPLETE",
            {"name": skill_meta.name},
            correlation_id=correlation_id,
        )
        return result

    async def _run_llm(
        self, skill_meta: SkillMeta, context: SkillContext, correlation_id: str = ""
    ) -> dict:
        """Execute a Skill via 3-phase pipeline: GATHER → LLM → APPLY."""
        # Phase 1: GATHER — read vault notes if read_context is defined
        vault_context = await self._gather_vault_context(skill_meta.read_context, context)
        await emit_event(
            self._event_bus,
            "SKILL_GATHER_COMPLETE",
            {"name": skill_meta.name, "context_length": len(vault_context)},
            correlation_id=correlation_id,
        )

        # Phase 2: LLM CALL — build messages and call LLM
        system, messages = self._build_messages(skill_meta, vault_context, context.input_data)
        response = await context.llm.chat(system=system, messages=messages)
        await emit_event(
            self._event_bus,
            "SKILL_LLM_RESPONSE",
            {"name": skill_meta.name, "response_length": len(response)},
            correlation_id=correlation_id,
        )

        # Phase 3: APPLY — write output to vault if output_target is defined
        result = await self._apply_output(skill_meta, context, response)
        await emit_event(
            self._event_bus,
            "SKILL_APPLY_COMPLETE",
            {"name": skill_meta.name, "has_output": "output_path" in result},
            correlation_id=correlation_id,
        )
        return result

    async def _gather_vault_context(self, read_dirs: list[str], context: SkillContext) -> str:
        """Read vault notes and build a context string for LLM.

        Uses index-based retrieval when a retriever is available,
        falling back to the original sequential read on failure or when
        the retriever is not configured.
        """
        if not read_dirs:
            return ""

        if self._retriever:
            query = ""
            if context.input_data:
                query = str(context.input_data)[:500]
            if not query:
                query = " ".join(read_dirs)
            try:
                return await self._retriever.retrieve(
                    query=query,
                    context_dirs=read_dirs,
                    max_chars=_MAX_CONTEXT_CHARS,
                    top_k=_MAX_NOTES_PER_DIR,
                )
            except Exception:
                logger.warning("index_gather_failed_fallback", exc_info=True)

        parts: list[str] = []
        total_chars = 0

        for subdir in read_dirs:
            if total_chars >= _MAX_CONTEXT_CHARS:
                break
            note_paths = await context.garden.read_notes(subdir)
            for path in note_paths[:_MAX_NOTES_PER_DIR]:
                if total_chars >= _MAX_CONTEXT_CHARS:
                    break
                try:
                    text = await context.garden.read_note_content(path)
                    remaining = _MAX_CONTEXT_CHARS - total_chars
                    parts.append(text[:remaining])
                    total_chars += len(parts[-1])
                except (OSError, VaultPathError):
                    logger.warning("gather_read_failed", path=str(path))

        return "\n---\n".join(parts)

    def _build_messages(
        self,
        skill_meta: SkillMeta,
        vault_context: str,
        input_data: dict | None,
    ) -> tuple[str, list[dict]]:
        """Build system prompt and user message for LLM call."""
        identity = ""
        if self._prompt_registry:
            with contextlib.suppress(KeyError):
                identity = self._prompt_registry.get("system")

        if skill_meta.system_prompt:
            skill_prompt = skill_meta.system_prompt
        elif self._prompt_registry:
            try:
                skill_prompt = self._prompt_registry.render(
                    "skill",
                    skill_name=skill_meta.name,
                    description=skill_meta.description,
                )
            except KeyError:
                skill_prompt = self._default_prompt(skill_meta)
        else:
            skill_prompt = self._default_prompt(skill_meta)

        system = f"{identity}\n\n{skill_prompt}".strip() if identity else skill_prompt
        if skill_meta.output_format == "json":
            system += "\nReturn your response as valid JSON."

        user_parts: list[str] = []
        if vault_context:
            user_parts.append(f"## Reference Notes\n{vault_context}")
        if input_data:
            formatted = json.dumps(input_data, default=str, ensure_ascii=False)
            user_parts.append(f"## Input Data\n{formatted}")
        user_content = "\n\n".join(user_parts) or "(no data)"

        return system, [{"role": "user", "content": user_content}]

    @staticmethod
    def _default_prompt(skill_meta: SkillMeta) -> str:
        return (
            f"You are executing the '{skill_meta.name}' skill.\n"
            f"Description: {skill_meta.description}\n"
            f"Process the input data and return a structured result."
        )

    async def _apply_output(
        self, skill_meta: SkillMeta, context: SkillContext, response: str
    ) -> dict:
        """Write LLM output to vault based on output_target."""
        if not skill_meta.output_target:
            return {"llm_response": response}

        content = response
        if skill_meta.output_format == "json":
            content = _strip_json_fence(response)

        if skill_meta.output_target is OutputTarget.GARDEN:
            path = await context.garden.write_garden(
                {
                    "title": f"{skill_meta.name} output",
                    "content": content,
                    "note_type": skill_meta.output_note_type,
                    "source": skill_meta.name,
                }
            )
            return {"llm_response": response, "output_path": str(path)}

        if skill_meta.output_target is OutputTarget.SEEDS:
            data: dict = {"content": content, "source": skill_meta.name}
            json_parse_error = False
            if skill_meta.output_format == "json":
                try:
                    parsed = json.loads(content)
                    data = (
                        parsed
                        if isinstance(parsed, dict)
                        else {"content": parsed, "source": skill_meta.name}
                    )
                except json.JSONDecodeError:
                    json_parse_error = True
                    logger.warning(
                        "json_parse_failed",
                        skill=skill_meta.name,
                        content_preview=content[:100],
                    )
            path = await context.garden.write_seed(skill_meta.name, data)
            result: dict = {"llm_response": response, "output_path": str(path)}
            if json_parse_error:
                result["json_parse_error"] = True
            return result

        from typing import assert_never

        assert_never(skill_meta.output_target)

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        """Remove markdown code fences around JSON content."""
        return _strip_json_fence(text)
