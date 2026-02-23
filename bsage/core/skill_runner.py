"""SkillRunner — executes skills (Python or LLM-based) with context injection."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

import structlog

from bsage.core.credential_store import CredentialStore
from bsage.core.exceptions import CredentialNotFoundError, SkillRunError
from bsage.core.skill_loader import OutputTarget
from bsage.garden.vault import VaultPathError

if TYPE_CHECKING:
    from bsage.core.prompt_registry import PromptRegistry
    from bsage.core.skill_context import SkillContext
    from bsage.core.skill_loader import SkillMeta

# Maximum number of notes to read per vault subdirectory during GATHER phase.
_MAX_NOTES_PER_DIR = 20
# Maximum total characters of vault context to feed into the LLM prompt.
_MAX_CONTEXT_CHARS = 50_000

logger = structlog.get_logger(__name__)

_BACKTICK_FENCE_RE = re.compile(r"```+(?:\s*json)?\s*\n(.*?)```+", re.DOTALL | re.IGNORECASE)
_TILDE_FENCE_RE = re.compile(r"~~~+(?:\s*json)?\s*\n(.*?)~~~+", re.DOTALL | re.IGNORECASE)


def _strip_json_fence(text: str) -> str:
    """Remove markdown code fences around JSON content.

    Handles fences with language tags, variable-length fence markers,
    and prose before/after the fenced block.
    """
    match = _BACKTICK_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()

    match = _TILDE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()

    return text.strip()


class SkillRunner:
    """Dispatches skill execution to either Python code or LLM-based processing."""

    def __init__(
        self,
        skills_dir: Path,
        credential_store: CredentialStore | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self._skills_dir = skills_dir
        self._credential_store = credential_store
        self._prompt_registry = prompt_registry

    async def run(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Execute a skill and return the result dict.

        For skills with an entrypoint, loads and runs the Python module.
        For yaml-only skills, delegates to LLM-based execution.

        Raises:
            SkillRunError: On execution failure.
        """
        logger.info("skill_run_start", name=skill_meta.name, category=skill_meta.category)

        await self._auto_inject_credentials(skill_meta.name, context)

        try:
            if skill_meta.entrypoint:
                result = await self._run_python(skill_meta, context)
            else:
                result = await self._run_llm(skill_meta, context)
        except SkillRunError:
            raise
        except Exception as exc:
            raise SkillRunError(f"Skill '{skill_meta.name}' execution failed: {exc}") from exc

        logger.info("skill_run_complete", name=skill_meta.name)
        return result

    async def run_notify(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Execute the notification entrypoint of a skill.

        Input skills with a notification_entrypoint can send messages back
        through the same channel they receive from (e.g. Telegram bot).

        Raises:
            SkillRunError: If the skill has no notification_entrypoint or execution fails.
        """
        if not skill_meta.notification_entrypoint:
            raise SkillRunError(f"Skill '{skill_meta.name}' has no notification_entrypoint")

        logger.info("skill_notify_start", name=skill_meta.name)

        await self._auto_inject_credentials(skill_meta.name, context)

        try:
            result = await self._run_entrypoint(
                skill_meta.name, skill_meta.notification_entrypoint, context
            )
        except SkillRunError:
            raise
        except Exception as exc:
            raise SkillRunError(f"Skill '{skill_meta.name}' notification failed: {exc}") from exc

        logger.info("skill_notify_complete", name=skill_meta.name)
        return result

    async def _auto_inject_credentials(self, skill_name: str, context: SkillContext) -> None:
        """Inject credentials into context.credentials if available.

        Looks up credentials from the internal CredentialStore and sets
        context.credentials to the resolved dict for the skill to use directly.
        """
        if self._credential_store is None:
            return
        try:
            creds = await self._credential_store.get(skill_name)
            context.credentials = dict(creds)
        except CredentialNotFoundError:
            pass  # No credentials for this skill is normal

    async def _run_python(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Load and execute a Python skill module dynamically."""
        if not skill_meta.entrypoint:
            raise SkillRunError(f"Skill '{skill_meta.name}' has no entrypoint")
        return await self._run_entrypoint(skill_meta.name, skill_meta.entrypoint, context)

    async def _run_entrypoint(
        self, skill_name: str, entrypoint: str, context: SkillContext
    ) -> dict:
        """Parse an entrypoint string, load the module, and call the function."""
        parts = entrypoint.split("::")
        if len(parts) != 2:  # noqa: PLR2004
            raise SkillRunError(
                f"Invalid entrypoint format '{entrypoint}'. Expected 'module.py::function'."
            )
        module_file, func_name = parts
        module_path = self._skills_dir / skill_name / module_file

        # Ensure resolved path stays within the skills directory
        if not module_path.resolve().is_relative_to(self._skills_dir.resolve()):
            raise SkillRunError(f"Path traversal detected in skill '{skill_name}'")

        if not module_path.exists():
            raise SkillRunError(f"Skill module not found: {module_path}")

        spec = importlib.util.spec_from_file_location("skill_module", module_path)
        if spec is None or spec.loader is None:
            raise SkillRunError(f"Cannot load skill module: {module_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        func = getattr(module, func_name, None)
        if func is None:
            raise SkillRunError(f"Function '{func_name}' not found in {module_path}")

        return await func(context)

    async def _run_llm(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Execute a yaml-only skill via 3-phase pipeline: GATHER → LLM → APPLY."""
        # Phase 1: GATHER — read vault notes if read_context is defined
        vault_context = await self._gather_vault_context(skill_meta.read_context, context)

        # Phase 2: LLM CALL — build messages and call LLM
        system, messages = self._build_messages(skill_meta, vault_context, context.input_data)
        response = await context.llm.chat(system=system, messages=messages)

        # Phase 3: APPLY — write output to vault if output_target is defined
        return await self._apply_output(skill_meta, context, response)

    async def _gather_vault_context(self, read_dirs: list[str], context: SkillContext) -> str:
        """Read vault notes and build a context string for LLM."""
        if not read_dirs:
            return ""

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
        # System: identity + skill-specific instructions
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
                skill_prompt = (
                    f"You are executing the '{skill_meta.name}' skill.\n"
                    f"Description: {skill_meta.description}\n"
                    f"Process the input data and return a structured result."
                )
        else:
            skill_prompt = (
                f"You are executing the '{skill_meta.name}' skill.\n"
                f"Description: {skill_meta.description}\n"
                f"Process the input data and return a structured result."
            )

        system = f"{identity}\n\n{skill_prompt}".strip() if identity else skill_prompt
        if skill_meta.output_format == "json":
            system += "\nReturn your response as valid JSON."

        # User: data (vault context + input)
        user_parts: list[str] = []
        if vault_context:
            user_parts.append(f"## Reference Notes\n{vault_context}")
        if input_data:
            formatted = json.dumps(input_data, default=str, ensure_ascii=False)
            user_parts.append(f"## Input Data\n{formatted}")
        user_content = "\n\n".join(user_parts) or "(no data)"

        return system, [{"role": "user", "content": user_content}]

    async def _apply_output(
        self, skill_meta: SkillMeta, context: SkillContext, response: str
    ) -> dict:
        """Write LLM output to vault based on output_target."""
        if not skill_meta.output_target:
            return {"llm_response": response}

        content = response
        if skill_meta.output_format == "json":
            content = self._strip_json_fence(response)

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
            data = {"content": content, "source": skill_meta.name}
            json_parse_error = False
            if skill_meta.output_format == "json":
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        data = parsed
                    else:
                        data = {"content": parsed, "source": skill_meta.name}
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

        else:
            assert_never(skill_meta.output_target)

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        """Remove markdown code fences around JSON content."""
        return _strip_json_fence(text)
