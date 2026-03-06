"""Runner — unified dispatcher that routes execution to PluginRunner or SkillRunner."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from bsage.core.exceptions import PluginRunError

if TYPE_CHECKING:
    from bsage.core.plugin_loader import PluginMeta
    from bsage.core.plugin_runner import PluginRunner
    from bsage.core.skill_context import SkillContext
    from bsage.core.skill_loader import SkillMeta
    from bsage.core.skill_runner import SkillRunner

logger = structlog.get_logger(__name__)


class Runner:
    """Unified execution dispatcher for Plugins and Skills.

    Accepts both ``PluginMeta`` and ``SkillMeta`` and dispatches to the
    appropriate runner (PluginRunner for Python code, SkillRunner for LLM
    pipelines).  This allows the scheduler and AgentLoop to use a single
    runner interface regardless of meta type.
    """

    def __init__(self, plugin_runner: PluginRunner, skill_runner: SkillRunner) -> None:
        self._plugin_runner = plugin_runner
        self._skill_runner = skill_runner

    async def run(self, meta: PluginMeta | SkillMeta, context: SkillContext) -> dict:
        """Dispatch execution to the correct runner based on meta type."""
        from bsage.core.plugin_loader import PluginMeta as _PluginMeta  # avoid circular

        if isinstance(meta, _PluginMeta):
            return await self._plugin_runner.run(meta, context)
        return await self._skill_runner.run(meta, context)

    async def run_notify(self, meta: PluginMeta | SkillMeta, context: SkillContext) -> dict:
        """Dispatch notification to the PluginRunner.

        Skills do not support bidirectional notifications — only Plugins do.

        Raises:
            PluginRunError: If called with a SkillMeta or the plugin has no notify handler.
        """
        from bsage.core.plugin_loader import PluginMeta as _PluginMeta

        if isinstance(meta, _PluginMeta):
            return await self._plugin_runner.run_notify(meta, context)
        raise PluginRunError("Skills do not support notification entrypoints")
