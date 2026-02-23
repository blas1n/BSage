"""AgentLoop — orchestrates Skill execution via trigger matching."""

from __future__ import annotations

import json
from typing import Any

import structlog

from bsage.core.notification import NotificationInterface
from bsage.core.safe_mode import SafeModeGuard
from bsage.core.skill_context import LLMClient, SkillContext
from bsage.core.skill_loader import SkillMeta
from bsage.core.skill_runner import SkillRunner
from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)


class AgentLoop:
    """Orchestrates Skill execution via trigger matching.

    Flow:
    1. Write raw input to seeds
    2. Find process skills triggered by on_input
    3. Ask LLM which on_demand skills should also run
    4. SafeMode check → SkillRunner.run → write action
    """

    def __init__(
        self,
        registry: dict[str, SkillMeta],
        skill_runner: SkillRunner,
        safe_mode_guard: SafeModeGuard,
        garden_writer: GardenWriter,
        llm_client: LLMClient,
        notification: NotificationInterface | None = None,
    ) -> None:
        self._registry = registry
        self._skill_runner = skill_runner
        self._safe_mode_guard = safe_mode_guard
        self._garden_writer = garden_writer
        self._llm_client = llm_client
        self._notification = notification

    async def on_input(self, skill_name: str, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Process input from an InputSkill and run triggered skills.

        Args:
            skill_name: Name of the InputSkill that produced the data.
            raw_data: Raw data collected by the InputSkill.

        Returns:
            List of result dicts from each executed skill.
        """
        logger.info("agent_loop_input", skill_name=skill_name)

        # 1. Write raw data to seeds
        await self._garden_writer.write_seed(skill_name, raw_data)

        # 2. Find process skills with trigger.type == on_input
        triggered = self._find_triggered_skills(skill_name)

        # 3. Ask LLM which on_demand skills should also run
        on_demand = await self._decide_on_demand_skills(skill_name, raw_data)

        # 4. Execute each skill
        results: list[dict] = []
        for meta in triggered + on_demand:
            approved = await self._safe_mode_guard.check(meta)
            if not approved:
                logger.warning("skill_rejected_by_safe_mode", name=meta.name)
                continue

            context = self.build_context(input_data=raw_data)
            result = await self._skill_runner.run(meta, context)
            results.append(result)

            summary = json.dumps(result, default=str)
            await self._garden_writer.write_action(meta.name, summary)

        logger.info(
            "agent_loop_complete",
            skill_name=skill_name,
            skills_run=len(results),
        )
        return results

    def _find_triggered_skills(self, source_name: str) -> list[SkillMeta]:
        """Find process skills with trigger.type == on_input matching source."""
        result = []
        for meta in self._registry.values():
            if meta.category != "process" or not meta.trigger:
                continue
            if meta.trigger.get("type") != "on_input":
                continue
            sources = meta.trigger.get("sources")
            if sources is None or source_name in sources:
                result.append(meta)
        return result

    async def _decide_on_demand_skills(
        self, source_name: str, raw_data: dict[str, Any]
    ) -> list[SkillMeta]:
        """Use LLM to decide which on_demand process skills to run."""
        on_demand = [
            m
            for m in self._registry.values()
            if m.category == "process" and (not m.trigger or m.trigger.get("type") == "on_demand")
        ]

        if not on_demand:
            return []

        skill_descriptions = "\n".join(
            f"- {m.name}: {m.description}"
            + (f" (hint: {m.trigger['hint']})" if m.trigger and m.trigger.get("hint") else "")
            for m in on_demand
        )

        system = (
            "You are BSage's skill router. Given input from a skill, "
            "decide which on-demand ProcessSkill(s) should run.\n"
            f"Available on-demand skills:\n{skill_descriptions}\n\n"
            "Respond with ONLY the skill name(s), one per line. "
            "If none are appropriate, respond with 'none'."
        )
        messages = [
            {
                "role": "user",
                "content": (
                    f"Input from '{source_name}':\n"
                    f"```json\n{json.dumps(raw_data, default=str)}\n```\n\n"
                    "Which skill(s) should handle this?"
                ),
            }
        ]

        response = await self._llm_client.chat(system=system, messages=messages)

        on_demand_names = {m.name for m in on_demand}
        selected = []
        for line in response.strip().splitlines():
            name = line.strip().lower()
            if name and name != "none" and name in on_demand_names:
                selected.append(self._registry[name])

        logger.info("llm_on_demand_decision", selected=[m.name for m in selected])
        return selected

    def get_skill(self, name: str) -> SkillMeta:
        """Look up a skill by name from the registry.

        Framework API — used by Scheduler.

        Raises:
            KeyError: If the skill is not registered.
        """
        return self._registry[name]

    def build_context(self, input_data: dict[str, Any] | None = None) -> SkillContext:
        """Create a SkillContext with all dependencies injected.

        Framework API — used by Scheduler and internal orchestration.
        """
        return SkillContext(
            garden=self._garden_writer,
            llm=self._llm_client,
            config={},
            logger=structlog.get_logger("skill"),
            input_data=input_data,
            notify=self._notification,
        )

    async def write_action(self, skill_name: str, summary: str) -> None:
        """Write an action log entry for a skill execution.

        Framework API — used by Scheduler.
        """
        await self._garden_writer.write_action(skill_name, summary)
