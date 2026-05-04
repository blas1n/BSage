"""PluginRunner — executes @plugin-decorated Python functions with context injection."""

from __future__ import annotations

import uuid

import jsonschema
import structlog

from bsage.core.events import emit_event
from bsage.core.exceptions import CredentialNotFoundError, MissingCredentialError, PluginRunError

if __import__("typing").TYPE_CHECKING:
    from bsage.core.credential_store import CredentialStore
    from bsage.core.events import EventBus
    from bsage.core.plugin_loader import PluginMeta
    from bsage.core.skill_context import SkillContext

logger = structlog.get_logger(__name__)


class PluginRunner:
    """Executes plugins by calling their @plugin-decorated execute/notify functions."""

    def __init__(
        self,
        credential_store: CredentialStore | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._credential_store = credential_store
        self._event_bus = event_bus

    async def run(self, meta: PluginMeta, context: SkillContext) -> dict:
        """Execute a plugin's main entrypoint and return the result dict.

        Raises:
            PluginRunError: On execution failure.
        """
        logger.info("plugin_run_start", name=meta.name, category=meta.category)
        correlation_id = str(uuid.uuid4())

        await emit_event(
            self._event_bus,
            "PLUGIN_RUN_START",
            {"name": meta.name, "category": meta.category},
            correlation_id=correlation_id,
        )

        await self._auto_inject_credentials(meta, context)
        self._validate_input_schema(meta, context)

        if meta._execute_fn is None:
            raise PluginRunError(f"Plugin '{meta.name}' has no execute function")

        plugin_context = self._restrict_garden(context)

        try:
            result = await meta._execute_fn(plugin_context)
        except PluginRunError:
            await emit_event(
                self._event_bus,
                "PLUGIN_RUN_ERROR",
                {"name": meta.name, "error": "execution failed"},
                correlation_id=correlation_id,
            )
            raise
        except Exception as exc:
            await emit_event(
                self._event_bus,
                "PLUGIN_RUN_ERROR",
                {"name": meta.name, "error": str(exc)},
                correlation_id=correlation_id,
            )
            raise PluginRunError(f"Plugin '{meta.name}' execution failed: {exc}") from exc

        logger.info("plugin_run_complete", name=meta.name)
        await emit_event(
            self._event_bus,
            "PLUGIN_RUN_COMPLETE",
            {"name": meta.name, "result_keys": list(result.keys())},
            correlation_id=correlation_id,
        )
        return result

    async def run_notify(self, meta: PluginMeta, context: SkillContext) -> dict:
        """Execute a plugin's notification handler.

        Raises:
            PluginRunError: If the plugin has no notify function or execution fails.
        """
        if meta._notify_fn is None:
            raise PluginRunError(f"Plugin '{meta.name}' has no notification handler")

        logger.info("plugin_notify_start", name=meta.name)
        correlation_id = str(uuid.uuid4())

        await emit_event(
            self._event_bus,
            "PLUGIN_NOTIFY_START",
            {"name": meta.name},
            correlation_id=correlation_id,
        )

        await self._auto_inject_credentials(meta, context)

        plugin_context = self._restrict_garden(context)

        try:
            result = await meta._notify_fn(plugin_context)
        except PluginRunError:
            await emit_event(
                self._event_bus,
                "PLUGIN_NOTIFY_ERROR",
                {"name": meta.name, "error": "notification failed"},
                correlation_id=correlation_id,
            )
            raise
        except Exception as exc:
            await emit_event(
                self._event_bus,
                "PLUGIN_NOTIFY_ERROR",
                {"name": meta.name, "error": str(exc)},
                correlation_id=correlation_id,
            )
            raise PluginRunError(f"Plugin '{meta.name}' notification failed: {exc}") from exc

        logger.info("plugin_notify_complete", name=meta.name)
        await emit_event(
            self._event_bus,
            "PLUGIN_NOTIFY_COMPLETE",
            {"name": meta.name},
            correlation_id=correlation_id,
        )
        return result

    @staticmethod
    def _restrict_garden(context: SkillContext) -> SkillContext:
        """Return a SkillContext with garden wrapped to seed-only access.

        External plugin code is not allowed to mutate ``garden/`` directly.
        It must submit a seed and let :class:`IngestCompiler` produce the
        garden notes. This wrapper enforces that contract at runtime so
        callers see a clear ``PermissionError`` if they try to call
        ``write_garden`` / ``update_note`` / ``append_to_note`` etc.
        """
        from dataclasses import is_dataclass, replace

        from bsage.core.skill_context import RestrictedPluginGarden

        if isinstance(context.garden, RestrictedPluginGarden):
            return context
        wrapped = RestrictedPluginGarden(context.garden)
        if is_dataclass(context):
            return replace(context, garden=wrapped)
        # Fallback for non-dataclass contexts (e.g. MagicMock in tests):
        # mutate in place. Callers who care about isolation should pass a
        # real SkillContext.
        context.garden = wrapped
        return context

    async def _auto_inject_credentials(self, meta: PluginMeta, context: SkillContext) -> None:
        """Inject credentials into context and validate required fields are present."""
        if self._credential_store is None:
            return

        required_fields = [f["name"] for f in (meta.credentials or []) if f.get("required", True)]

        try:
            creds = await self._credential_store.get(meta.name)
            context.credentials = dict(creds)
        except CredentialNotFoundError:
            if required_fields:
                raise MissingCredentialError(
                    f"Plugin '{meta.name}' requires credentials: {required_fields}. "
                    f"Run: bsage setup {meta.name}"
                ) from None
            return

        missing = [f for f in required_fields if f not in context.credentials]
        if missing:
            raise MissingCredentialError(
                f"Plugin '{meta.name}' missing required credential fields: {missing}. "
                f"Run: bsage setup {meta.name}"
            )

    @staticmethod
    def _validate_input_schema(meta: PluginMeta, context: SkillContext) -> None:
        """Validate context.input_data against meta.input_schema if defined."""
        if meta.input_schema is None:
            return

        data = context.input_data
        if data is None:
            raise PluginRunError(
                f"Plugin '{meta.name}' requires input_data matching input_schema, "
                f"but input_data is None"
            )

        try:
            jsonschema.validate(instance=data, schema=meta.input_schema)
        except jsonschema.ValidationError as exc:
            raise PluginRunError(
                f"Plugin '{meta.name}' input_schema validation failed: {exc.message}"
            ) from exc
        except jsonschema.SchemaError as exc:
            raise PluginRunError(
                f"Plugin '{meta.name}' has an invalid input_schema: {exc.message}"
            ) from exc
