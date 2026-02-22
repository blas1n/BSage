"""SkillRunner — executes skills (Python or LLM-based) with context injection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from bsage.core.exceptions import SkillRunError

if TYPE_CHECKING:
    from bsage.core.skill_context import SkillContext
    from bsage.core.skill_loader import SkillMeta

logger = structlog.get_logger(__name__)


class SkillRunner:
    """Dispatches skill execution to either Python code or LLM-based processing."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir

    async def run(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Execute a skill and return the result dict.

        For skills with an entrypoint, loads and runs the Python module.
        For yaml-only skills, delegates to LLM-based execution.
        Validates connector requirements before execution.

        Raises:
            SkillRunError: On execution failure or missing connector.
        """
        logger.info("skill_run_start", name=skill_meta.name, category=skill_meta.category)

        # Check connector requirement
        if skill_meta.requires_connector:
            try:
                await context.connector(skill_meta.requires_connector)
            except Exception as exc:
                raise SkillRunError(
                    f"Skill '{skill_meta.name}' requires connector "
                    f"'{skill_meta.requires_connector}' which is not available"
                ) from exc

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

    async def _run_python(self, skill_meta: SkillMeta, context: SkillContext) -> dict:
        """Load and execute a Python skill module dynamically."""
        assert skill_meta.entrypoint
        parts = skill_meta.entrypoint.split("::")
        if len(parts) != 2:  # noqa: PLR2004
            raise SkillRunError(
                f"Invalid entrypoint format '{skill_meta.entrypoint}'. "
                "Expected 'module.py::function'."
            )
        module_file, func_name = parts
        module_path = self._skills_dir / skill_meta.name / module_file

        # Ensure resolved path stays within the skills directory
        if not module_path.resolve().is_relative_to(self._skills_dir.resolve()):
            raise SkillRunError(f"Path traversal detected in skill '{skill_meta.name}'")

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
        """Execute a yaml-only skill via LLM chat."""
        system = (
            f"You are executing the '{skill_meta.name}' skill.\n"
            f"Description: {skill_meta.description}\n"
            f"Process the input data and return a structured result."
        )
        input_str = str(context.input_data) if context.input_data else "(no input data)"
        messages = [{"role": "user", "content": input_str}]

        response = await context.llm.chat(system=system, messages=messages)
        return {"llm_response": response}
