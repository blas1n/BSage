"""AgentLoop — orchestrates Plugin/Skill execution via trigger matching and tool use."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any

import structlog

from bsage.core.chat_bridge import ReplyFn
from bsage.core.events import emit_event
from bsage.core.exceptions import MissingCredentialError
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runner import Runner
from bsage.core.safe_mode import SafeModeGuard
from bsage.core.skill_context import LLMClient, SchedulerInterface, SkillContext
from bsage.garden.writer import (
    APPEND_NOTE_TOOL,
    DELETE_NOTE_TOOL,
    SEARCH_VAULT_TOOL,
    UPDATE_NOTE_TOOL,
    WRITE_NOTE_TOOL,
    WRITE_SEED_TOOL,
    GardenWriter,
)

if TYPE_CHECKING:
    from bsage.core.events import EventBus
    from bsage.core.plugin_loader import PluginMeta
    from bsage.core.runtime_config import RuntimeConfig
    from bsage.core.skill_loader import SkillMeta
    from bsage.garden.retriever import VaultRetriever

logger = structlog.get_logger(__name__)


class AgentLoop:
    """Orchestrates Plugin/Skill execution via trigger matching and tool use.

    Plugins with ``input_schema`` are exposed as LLM tools so the model
    can invoke them directly — both during interactive chat and when
    routing on-demand skills for automated input processing.
    """

    def __init__(
        self,
        registry: dict[str, PluginMeta | SkillMeta],
        runner: Runner,
        safe_mode_guard: SafeModeGuard,
        garden_writer: GardenWriter,
        llm_client: LLMClient,
        prompt_registry: PromptRegistry | None = None,
        event_bus: EventBus | None = None,
        on_refresh: Callable[[], Awaitable[None]] | None = None,
        runtime_config: RuntimeConfig | None = None,
        retriever: VaultRetriever | None = None,
        scheduler_adapter: SchedulerInterface | None = None,
    ) -> None:
        self._registry = registry
        self._runner = runner
        self._safe_mode_guard = safe_mode_guard
        self._garden_writer = garden_writer
        self._llm_client = llm_client
        self._prompt_registry = prompt_registry
        self._event_bus = event_bus
        self._on_refresh = on_refresh
        self._runtime_config = runtime_config
        self._retriever = retriever
        self._scheduler_adapter = scheduler_adapter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(self, system: str, messages: list[dict]) -> str:
        """Interactive chat with tool-use plugin execution.

        The LLM sees available plugins and built-in tools (write-note) and
        can call them during the conversation.
        """
        if self._on_refresh:
            await self._on_refresh()
        tools = self._build_tools()
        return await self._llm_client.chat(
            system=system,
            messages=messages,
            tools=tools,
            tool_handler=self._handle_tool_call,
        )

    async def on_input(self, plugin_name: str, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Process input from a Plugin and run triggered entries.

        1. Preserve raw data in input-log, then refine and write to seeds.
        2. Run deterministic on_input-triggered plugins/skills.
        3. Let LLM decide and execute on-demand plugins via tool use.
        """
        if self._on_refresh:
            await self._on_refresh()
        logger.info("agent_loop_input", plugin_name=plugin_name)
        await emit_event(self._event_bus, "INPUT_RECEIVED", {"plugin_name": plugin_name})

        # 1a. Preserve raw data in input-log (transparency)
        raw_summary = json.dumps(raw_data, default=str, ensure_ascii=False)
        await self._garden_writer.write_input_log(plugin_name, raw_summary)

        # 1b. Refine and write to seeds
        refined = await self._refine_seed(plugin_name, raw_data)
        await self._garden_writer.write_seed(plugin_name, refined)

        # 2. Run deterministic on_input-triggered plugins/skills
        triggered = self._find_triggered(plugin_name)
        results: list[dict] = []
        for meta in triggered:
            approved = await self._safe_mode_guard.check(meta)
            if not approved:
                logger.warning("entry_rejected_by_safe_mode", name=meta.name)
                continue
            context = self.build_context(input_data=raw_data, reply_via=plugin_name)
            try:
                result = await self._runner.run(meta, context)
            except MissingCredentialError:
                logger.warning("entry_skipped_missing_credentials", name=meta.name)
                continue
            results.append(result)
            summary = json.dumps(result, default=str)
            await self._garden_writer.write_action(meta.name, summary)

        # 3. Let LLM decide and execute on-demand plugins via tool use
        on_demand_results = await self._decide_on_demand(plugin_name, raw_data)
        results.extend(on_demand_results)

        logger.info(
            "agent_loop_complete",
            plugin_name=plugin_name,
            entries_run=len(results),
        )
        await emit_event(
            self._event_bus,
            "INPUT_COMPLETE",
            {"plugin_name": plugin_name, "entries_run": len(results)},
        )
        return results

    # ------------------------------------------------------------------
    # Seed refinement
    # ------------------------------------------------------------------

    _REFINE_PROMPT_FALLBACK = (
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

    @property
    def _refine_prompt(self) -> str:
        """Load seed-refiner prompt from PromptRegistry, falling back to inline."""
        if self._prompt_registry:
            try:
                return self._prompt_registry.get("seed-refiner")
            except KeyError:
                pass
        return self._REFINE_PROMPT_FALLBACK

    async def _refine_seed(self, plugin_name: str, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Refine raw input data using a lightweight LLM pass.

        Falls back to raw_data if refinement fails.
        """
        # If already structured (has title + content), skip refinement
        if "title" in raw_data and "content" in raw_data:
            return raw_data

        raw_text = json.dumps(raw_data, default=str, ensure_ascii=False)
        if len(raw_text) < 20:
            return raw_data

        response = ""
        try:
            response = await self._llm_client.chat(
                system=self._refine_prompt,
                messages=[{"role": "user", "content": raw_text}],
            )
            parsed = json.loads(response.strip())
            if isinstance(parsed, dict) and "title" in parsed and "content" in parsed:
                logger.info("seed_refined", plugin_name=plugin_name)
                return parsed
        except (json.JSONDecodeError, ValueError, TypeError, RuntimeError, OSError):
            logger.debug(
                "seed_refine_failed_using_raw",
                plugin_name=plugin_name,
                response_preview=response[:200],
                exc_info=True,
            )

        return raw_data

    # ------------------------------------------------------------------
    # Trigger matching
    # ------------------------------------------------------------------

    def _find_triggered(self, source_name: str) -> list[PluginMeta | SkillMeta]:
        """Find process entries with trigger.type == on_input matching source."""
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

    # ------------------------------------------------------------------
    # Tool use infrastructure (shared by chat and on_input)
    # ------------------------------------------------------------------

    def _build_tools(self) -> list[dict]:
        """Build OpenAI-format tool definitions including built-in and plugin tools.

        Only plugins present in ``runtime_config.enabled_entries`` are exposed.
        When no runtime_config is set, all eligible plugins are included.
        """
        from bsage.core.plugin_loader import PluginMeta

        enabled = self._runtime_config.enabled_entries if self._runtime_config else None
        tools: list[dict] = [
            WRITE_NOTE_TOOL,
            WRITE_SEED_TOOL,
            UPDATE_NOTE_TOOL,
            APPEND_NOTE_TOOL,
            DELETE_NOTE_TOOL,
            SEARCH_VAULT_TOOL,
        ]
        for meta in self._registry.values():
            if isinstance(meta, PluginMeta) and meta.category == "process" and meta.input_schema:
                if enabled is not None and meta.name not in enabled:
                    continue
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": meta.name,
                            "description": meta.description,
                            "parameters": meta.input_schema,
                        },
                    }
                )
        return tools

    @cached_property
    def _builtin_handlers(self) -> dict[str, Callable[[dict[str, Any]], Awaitable[Any]]]:
        """Map built-in tool names to their handler functions.

        Each handler takes ``args`` and returns a result (dict or str).
        The dispatch loop in ``_handle_tool_call`` wraps the common
        action-log / event / error-handling logic around every handler.
        """
        return {
            "write-note": self._garden_writer.handle_write_note,
            "write-seed": self._garden_writer.handle_write_seed,
            "update-note": self._garden_writer.handle_update_note,
            "append-note": self._garden_writer.handle_append_note,
            "delete-note": self._garden_writer.handle_delete_note,
            "search-vault": self._handle_search_vault,
        }

    async def _handle_search_vault(self, args: dict[str, Any]) -> dict[str, Any] | str:
        """Handle a search-vault tool call."""
        query = args["query"]
        dirs = args.get("context_dirs")
        max_results = args.get("max_results", 10)
        if self._retriever:
            return await self._retriever.search(query, context_dirs=dirs, top_k=max_results)
        return "(search not available — index not configured)"

    async def _handle_tool_call(self, tool_call_id: str, name: str, args: dict[str, Any]) -> str:
        """Execute an entry triggered by an LLM tool call.

        Built-in tools are dispatched via ``_builtin_handlers()``.
        Plugin tools go through SafeMode → Runner.run() → action log.
        """
        await emit_event(
            self._event_bus, "TOOL_CALL_START", {"tool_call_id": tool_call_id, "name": name}
        )

        handler = self._builtin_handlers.get(name)
        if handler is not None:
            try:
                result = await handler(args)
                result_str = result if isinstance(result, str) else json.dumps(result, default=str)
                summary = result_str[:200]
                await self._garden_writer.write_action(name, summary)
                await emit_event(
                    self._event_bus,
                    "TOOL_CALL_COMPLETE",
                    {"tool_call_id": tool_call_id, "name": name},
                )
                return result_str
            except Exception as exc:
                logger.exception("builtin_tool_failed", tool=name)
                return json.dumps({"error": str(exc)})

        meta = self._registry.get(name)
        if meta is None:
            return json.dumps({"error": f"Unknown plugin: {name}"})

        approved = await self._safe_mode_guard.check(meta)
        if not approved:
            logger.warning("entry_rejected_by_safe_mode", name=name)
            return json.dumps({"error": f"Plugin '{name}' rejected by safe mode"})

        try:
            context = self.build_context(input_data=args)
            result = await self._runner.run(meta, context)
            summary = json.dumps(result, default=str)[:200]
            await self._garden_writer.write_action(name, summary)
            await emit_event(
                self._event_bus,
                "TOOL_CALL_COMPLETE",
                {"tool_call_id": tool_call_id, "name": name},
            )
            return json.dumps(result, default=str)
        except MissingCredentialError as exc:
            logger.warning("tool_call_missing_credentials", name=name)
            return json.dumps({"error": str(exc)})
        except Exception as exc:
            logger.exception("tool_call_failed", name=name)
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # On-demand routing via tool use
    # ------------------------------------------------------------------

    async def _decide_on_demand(self, source_name: str, raw_data: dict[str, Any]) -> list[dict]:
        """Let LLM decide and execute on-demand entries via tool use.

        If on-demand plugins have input_schema, uses tool use so the LLM
        both decides AND executes in a single pass.  Falls back to the
        text-based routing for entries without input_schema.
        """
        from bsage.core.plugin_loader import PluginMeta

        on_demand = [
            m
            for m in self._registry.values()
            if m.category == "process" and (not m.trigger or m.trigger.get("type") == "on_demand")
        ]
        if not on_demand:
            return []

        # Build tool definitions for on-demand plugins with input_schema
        tools = []
        for m in on_demand:
            if isinstance(m, PluginMeta) and m.input_schema:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": m.name,
                            "description": m.description,
                            "parameters": m.input_schema,
                        },
                    }
                )

        system = self._build_router_prompt(on_demand)
        messages = [
            {
                "role": "user",
                "content": (
                    f"Input from '{source_name}':\n"
                    f"```json\n{json.dumps(raw_data, default=str)}\n```\n\n"
                    "Decide which plugin(s) should handle this and call them."
                ),
            }
        ]

        # Collect results from tool calls
        results: list[dict] = []

        if tools:
            # Tool use path: LLM decides and executes via tool calls
            async def _collecting_handler(
                tool_call_id: str, name: str, args: dict[str, Any]
            ) -> str:
                result_str = await self._handle_tool_call(tool_call_id, name, args)
                try:
                    results.append(json.loads(result_str))
                except json.JSONDecodeError:
                    results.append({"raw": result_str})
                return result_str

            await self._llm_client.chat(
                system=system,
                messages=messages,
                tools=tools,
                tool_handler=_collecting_handler,
            )
        else:
            # Fallback: text-based routing for entries without input_schema
            selected = await self._route_by_text(on_demand, system, messages)
            for meta in selected:
                approved = await self._safe_mode_guard.check(meta)
                if not approved:
                    continue
                context = self.build_context(input_data=raw_data, reply_via=source_name)
                result = await self._runner.run(meta, context)
                results.append(result)
                summary = json.dumps(result, default=str)
                await self._garden_writer.write_action(meta.name, summary)

        return results

    async def _route_by_text(
        self,
        on_demand: list[PluginMeta | SkillMeta],
        system: str,
        messages: list[dict],
    ) -> list[PluginMeta | SkillMeta]:
        """Fallback: text-based routing when no tools are available."""
        response = await self._llm_client.chat(system=system, messages=messages)
        on_demand_names = {m.name for m in on_demand}
        selected = []
        for line in response.strip().splitlines():
            name = line.strip().lower()
            if name and name != "none" and name in on_demand_names:
                selected.append(self._registry[name])
        logger.info("llm_on_demand_decision", selected=[m.name for m in selected])
        return selected

    def _build_router_prompt(self, on_demand: list[PluginMeta | SkillMeta]) -> str:
        """Build system prompt for on-demand routing."""
        descriptions = "\n".join(
            f"- {m.name}: {m.description}"
            + (f" (hint: {m.trigger['hint']})" if m.trigger and m.trigger.get("hint") else "")
            for m in on_demand
        )
        if self._prompt_registry:
            try:
                return self._prompt_registry.render("router", skill_descriptions=descriptions)
            except KeyError:
                pass
        return self._build_router_prompt_fallback(descriptions)

    @staticmethod
    def _build_router_prompt_fallback(descriptions: str) -> str:
        """Build router system prompt when PromptRegistry is unavailable."""
        return (
            "You are BSage's plugin router. Given input from a plugin, "
            "decide which on-demand process plugin(s) should run.\n"
            f"Available on-demand plugins:\n{descriptions}\n\n"
            "Respond with ONLY the plugin name(s), one per line. "
            "If none are appropriate, respond with 'none'."
        )

    # ------------------------------------------------------------------
    # Framework API
    # ------------------------------------------------------------------

    def get_entry(self, name: str) -> PluginMeta | SkillMeta:
        """Look up a plugin/skill by name from the registry.

        Raises:
            KeyError: If the entry is not registered.
        """
        return self._registry[name]

    def build_context(
        self,
        input_data: dict[str, Any] | None = None,
        reply_via: str | None = None,
    ) -> SkillContext:
        """Create a SkillContext with all dependencies injected.

        Args:
            input_data: Input payload for the skill.
            reply_via: Plugin name whose _notify_fn provides the reply channel.
        """
        reply_fn = self._make_reply_fn(reply_via) if reply_via else None
        chat_bridge = None
        if self._prompt_registry:
            from bsage.core.chat_bridge import ChatBridge

            chat_bridge = ChatBridge(
                agent_loop=self,
                garden_writer=self._garden_writer,
                prompt_registry=self._prompt_registry,
                retriever=self._retriever,
                reply_fn=reply_fn,
            )
        retriever_adapter = None
        if self._retriever:
            from bsage.core.skill_context import RetrieverAdapter

            retriever_adapter = RetrieverAdapter(self._retriever)

        event_emitter = None
        if self._event_bus:
            from bsage.core.events import EventEmitterAdapter

            event_emitter = EventEmitterAdapter(self._event_bus)

        return SkillContext(
            garden=self._garden_writer,
            llm=self._llm_client,
            config={},
            logger=structlog.get_logger("skill"),
            input_data=input_data,
            chat=chat_bridge,
            retriever=retriever_adapter,
            scheduler=self._scheduler_adapter,
            events=event_emitter,
        )

    def _make_reply_fn(self, source_name: str) -> ReplyFn | None:
        """Create a reply closure from the source plugin's _notify_fn."""
        from bsage.core.plugin_loader import PluginMeta

        meta = self._registry.get(source_name)
        if not isinstance(meta, PluginMeta) or meta._notify_fn is None:
            return None

        async def _reply(message: str) -> None:
            ctx = SkillContext(
                garden=self._garden_writer,
                llm=self._llm_client,
                config={},
                logger=structlog.get_logger("notify"),
                input_data={"message": message},
            )
            await self._runner.run_notify(meta, ctx)

        return _reply

    async def write_action(self, name: str, summary: str) -> None:
        """Write an action log entry for a plugin/skill execution."""
        await self._garden_writer.write_action(name, summary)
