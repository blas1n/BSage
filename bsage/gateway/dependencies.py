"""FastAPI dependency injection for the Gateway."""

from __future__ import annotations

import asyncio
import contextlib

import structlog

from bsage.core.agent_loop import AgentLoop
from bsage.core.chat_bridge import ChatBridge
from bsage.core.config import Settings
from bsage.core.credential_store import CredentialStore
from bsage.core.danger_analyzer import DangerAnalyzer
from bsage.core.events import EventBus
from bsage.core.llm import LiteLLMClient
from bsage.core.plugin_loader import PluginLoader
from bsage.core.plugin_runner import PluginRunner
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runner import Runner
from bsage.core.runtime_config import RuntimeConfig
from bsage.core.safe_mode import SafeModeGuard
from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillLoader
from bsage.core.skill_runner import SkillRunner
from bsage.core.tasks import spawn_task
from bsage.garden.audit_outbox import AiosqliteAuditOutbox, AiosqliteOutboxRelay
from bsage.garden.embedder import Embedder
from bsage.garden.file_index_reader import FileIndexReader
from bsage.garden.graph_extractor import GraphExtractor
from bsage.garden.graph_retriever import GraphRetriever
from bsage.garden.graph_store import GraphStore
from bsage.garden.ingest_compiler import IngestCompiler
from bsage.garden.llm_extractor import LLMExtractor
from bsage.garden.ontology import OntologyRegistry
from bsage.garden.retriever import VaultRetriever
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.garden.vector_store import VectorStore
from bsage.garden.writer import GardenWriter
from bsage.gateway.auth import create_auth_provider
from bsage.gateway.authz import combined_principal
from bsage.gateway.event_broadcaster import WebSocketEventBroadcaster
from bsage.gateway.ws import manager as ws_manager
from bsage.interface.ws_interface import WebSocketApprovalInterface

logger = structlog.get_logger(__name__)


class AppState:
    """Holds all initialized core components for the Gateway."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Runtime config (mutable, shared reference, persisted to JSON)
        # Store in credentials_dir (gitignored) — NOT vault_path (may be synced)
        persist_path = settings.credentials_dir / "runtime_config.json"
        self.runtime_config = RuntimeConfig.from_settings(settings, persist_path=persist_path)

        # EventBus + WebSocket broadcaster
        self.event_bus = EventBus()
        self._ws_broadcaster = WebSocketEventBroadcaster(manager=ws_manager)
        self.event_bus.subscribe(self._ws_broadcaster)

        # Sync manager (backends registered later by OutputPlugins)
        self.sync_manager = SyncManager(runtime_config=self.runtime_config)

        # Garden layer
        self.vault = Vault(settings.vault_path)

        # Phase Audit Batch 2 — raw aiosqlite audit outbox lives in its own
        # SQLite file under the vault (.bsage/audit_outbox.db) so emit calls
        # never contend with the knowledge-graph write queue. The relay reads
        # AuditSettings from env separately; tests/dev with no audit URL
        # configured leave the relay disabled (no-op).
        audit_outbox_path = settings.vault_path / ".bsage" / "audit_outbox.db"
        self.audit_outbox: AiosqliteAuditOutbox | None = AiosqliteAuditOutbox(audit_outbox_path)
        self.audit_relay: AiosqliteOutboxRelay | None = None

        # Phase 0 P0.5 — pass default tenant id so cron / migration writes
        # still satisfy the tenant column when no principal is available.
        self.garden_writer = GardenWriter(
            self.vault,
            sync_manager=self.sync_manager,
            event_bus=self.event_bus,
            default_tenant_id=settings.default_tenant_id or None,
            audit_outbox=self.audit_outbox,
        )

        # Credentials — Fernet-at-rest when an encryption key is configured.
        self.credential_store = CredentialStore(
            settings.credentials_dir,
            primary_key=settings.credential_encryption_key or None,
            retired_keys=settings.credential_encryption_retired_keys,
        )

        # LLM (reads from RuntimeConfig per-call)
        self.llm_client = LiteLLMClient(runtime_config=self.runtime_config)

        # danger_map populated in initialize() after plugin load_all()
        self._danger_map: dict[str, bool] = {}

        # Authentication
        # Legacy provider kept for back-compat (used by WS auth route + the
        # /auth/callback redirect helper). Phase 0 P0.5 routes the HTTP
        # principal through ``bsvibe_authz.combined_principal`` instead, which
        # accepts both user JWTs and audience-scoped service JWTs.
        self.auth_provider = create_auth_provider(settings)
        self.get_current_user = combined_principal

        # WebSocket approval interface for SafeMode in Gateway context
        self.ws_approval_interface = WebSocketApprovalInterface(manager=ws_manager)

        # SafeMode — danger_fn reads _danger_map (closure; populated post-load)
        self.safe_mode_guard = SafeModeGuard(
            runtime_config=self.runtime_config,
            interface=self.ws_approval_interface,
            danger_fn=lambda name: self._danger_map.get(name, False),
        )

        # Prompts
        self.prompt_registry = PromptRegistry(settings.prompts_dir)

        # DangerAnalyzer — auto-classifies plugins at load time
        danger_cache_path = settings.tmp_dir / "danger_analysis.json"

        async def _llm_fn(prompt: str) -> str:
            return await self.llm_client.chat(
                system="",
                messages=[{"role": "user", "content": prompt}],
            )

        self.danger_analyzer = DangerAnalyzer(
            cache_path=danger_cache_path,
            llm_fn=_llm_fn,
        )

        # Plugins
        self.plugin_loader = PluginLoader(
            settings.plugins_dir,
            danger_analyzer=self.danger_analyzer,
        )
        self.plugin_runner = PluginRunner(
            credential_store=self.credential_store, event_bus=self.event_bus
        )

        # Knowledge graph + ontology (created before index_reader so it can use ontology)
        graph_db_path = settings.vault_path / ".bsage" / "graph.db"
        self.graph_store = GraphStore(graph_db_path)
        ontology_path = settings.vault_path / ".bsage" / "ontology.yaml"
        self.ontology = OntologyRegistry(ontology_path)

        # Index reader for vault search (uses ontology for dynamic categories)
        self.index_reader = FileIndexReader(vault=self.vault, ontology=self.ontology)

        async def _llm_extract_fn(system: str, text: str) -> str:
            return await self.llm_client.chat(
                system=system, messages=[{"role": "user", "content": text}]
            )

        self.llm_extractor = LLMExtractor(llm_fn=_llm_extract_fn, ontology=self.ontology)
        self.graph_extractor = GraphExtractor(
            llm_extractor=self.llm_extractor, ontology=self.ontology
        )
        self.graph_retriever = GraphRetriever(self.graph_store, self.vault)

        # Vector embeddings (opt-in via EMBEDDING_MODEL env var)
        vector_db_path = settings.vault_path / ".bsage" / "vectors.db"
        self.vector_store = VectorStore(vector_db_path)
        self.embedder = Embedder(
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
            api_base=settings.embedding_api_base,
        )

        self.retriever = VaultRetriever(
            vault=self.vault,
            index_reader=self.index_reader,
            graph_retriever=self.graph_retriever,
            vector_store=self.vector_store if self.embedder.enabled else None,
            embedder=self.embedder if self.embedder.enabled else None,
        )

        # Skills
        self.skill_loader = SkillLoader(settings.skills_dir)
        self.skill_runner = SkillRunner(
            prompt_registry=self.prompt_registry,
            event_bus=self.event_bus,
            retriever=self.retriever,
        )

        # Unified runner dispatcher
        self.runner = Runner(
            plugin_runner=self.plugin_runner,
            skill_runner=self.skill_runner,
        )

        # Agent loop (registry populated after load_all)
        self.agent_loop: AgentLoop | None = None
        self.chat_bridge: ChatBridge | None = None
        self.scheduler: Scheduler | None = None

    @property
    def danger_map(self) -> dict[str, bool]:
        """Public accessor for the danger classification map."""
        return self._danger_map

    async def initialize(self) -> None:
        """Load plugins and skills, create AgentLoop, register triggers, start scheduler."""
        # Phase Audit Batch 2 — bring the outbox up before any route can fire
        # an emit. The relay is then started so background delivery races
        # with the request loop instead of stalling startup.
        if self.audit_outbox is not None:
            await self.audit_outbox.initialize()
            from bsvibe_audit import AuditSettings

            audit_settings = AuditSettings()
            self.audit_relay = AiosqliteOutboxRelay.from_settings(
                audit_settings, outbox=self.audit_outbox
            )
            await self.audit_relay.start()

        # Subscribe index subscriber to EventBus for write-time indexing
        from bsage.garden.graph_subscriber import GraphSubscriber
        from bsage.garden.index_subscriber import IndexSubscriber

        index_sub = IndexSubscriber(self.index_reader, self.vault)
        self.event_bus.subscribe(index_sub)

        # Initialize knowledge graph
        await self.graph_store.initialize()
        await self.ontology.load()

        # Initialize vector store (always, even if embedder disabled — no-op)
        if self.embedder.enabled:
            await self.vector_store.initialize()

            from bsage.garden.vector_subscriber import VectorSubscriber

            vector_sub = VectorSubscriber(
                self.vector_store,
                self.vault,
                self.embedder,
                max_embed_chars=self.settings.max_embed_chars,
            )
            self.event_bus.subscribe(vector_sub)
        graph_sub = GraphSubscriber(self.graph_store, self.vault, self.graph_extractor)
        self.event_bus.subscribe(graph_sub)

        # Background reindex to pick up manual vault edits (Obsidian, etc.).
        # ``spawn_task`` keeps a strong reference and routes failures through
        # structlog instead of asyncio's silent unawaited-task warning.
        self._reindex_task = spawn_task(self._background_reindex(), name="bsage.startup.reindex")
        self._graph_rebuild_task = spawn_task(
            self._background_graph_rebuild(), name="bsage.startup.graph_rebuild"
        )

        plugin_registry = await self.plugin_loader.load_all()
        skill_registry = await self.skill_loader.load_all()

        # Populate danger_map from plugin analysis results
        self._danger_map.update(self.plugin_loader.danger_map)

        # Merge into unified registry (plugins and skills share the same namespace)
        registry = {**plugin_registry, **skill_registry}
        logger.info(
            "registry_loaded",
            plugins=len(plugin_registry),
            skills=len(skill_registry),
        )

        # Ingest compiler (Karpathy-style ingest-time compilation)
        ingest_compiler: IngestCompiler | None = None
        if self.settings.ingest_compile_enabled:
            ingest_compiler = IngestCompiler(
                garden_writer=self.garden_writer,
                llm_client=self.llm_client,
                retriever=self.retriever,
                event_bus=self.event_bus,
                max_updates=self.settings.ingest_compile_max_updates,
            )

        self.agent_loop = AgentLoop(
            registry=registry,
            runner=self.runner,
            safe_mode_guard=self.safe_mode_guard,
            garden_writer=self.garden_writer,
            llm_client=self.llm_client,
            prompt_registry=self.prompt_registry,
            event_bus=self.event_bus,
            on_refresh=self._refresh_registry,
            runtime_config=self.runtime_config,
            retriever=self.retriever,
            graph_store=self.graph_store,
            ingest_compiler=ingest_compiler,
        )

        self.chat_bridge = ChatBridge(
            agent_loop=self.agent_loop,
            garden_writer=self.garden_writer,
            prompt_registry=self.prompt_registry,
            retriever=self.retriever,
            reply_fn=None,
            ingest_compiler=ingest_compiler,
        )

        self.runtime_config.rebuild_enabled(registry, self.credential_store)

        # Register output skills so they run on vault write events
        output_skills = [v for v in registry.values() if v.category == "output"]
        if output_skills:
            self.sync_manager.register_output_skills(
                output_skills, self.runner, self.agent_loop.build_context
            )

        self.scheduler = Scheduler(
            agent_loop=self.agent_loop,
            runner=self.runner,
            safe_mode_guard=self.safe_mode_guard,
            event_bus=self.event_bus,
        )
        self.scheduler.register_triggers(registry)

        # Register built-in maintenance tasks (not plugins)
        from bsage.core.maintenance import MaintenanceTasks

        maintenance = MaintenanceTasks(
            garden_writer=self.garden_writer,
            graph_store=self.graph_store,
            ontology=getattr(self, "ontology", None),
            settings=self.settings,
        )
        self.scheduler.register_maintenance(maintenance)

        self.scheduler.start()
        logger.info("gateway_initialized")

    async def _background_reindex(self) -> None:
        """Reconcile index with vault contents on startup.

        Runs in the background so it doesn't block server startup.
        Rebuilds the _index/ markdown files from vault notes.
        Retries once after 30 seconds on failure.
        """
        for attempt in range(2):
            try:
                count = await self.retriever.reindex_all()
                logger.info("startup_reindex_complete", indexed=count)
                return
            except Exception:
                logger.error("startup_reindex_failed", attempt=attempt + 1, exc_info=True)
                if attempt == 0:
                    await asyncio.sleep(30)

    async def _background_graph_rebuild(self) -> None:
        """Rebuild knowledge graph from existing vault notes on startup.

        Uses content hashing to skip notes that haven't changed since
        the last rebuild, avoiding O(N) DB writes on every restart.
        Retries once after 30 seconds on failure.
        """
        for attempt in range(2):
            try:
                count = await self.graph_store.rebuild_from_vault(self.vault, self.graph_extractor)
                logger.info("graph_rebuild_complete", **count)
                return
            except Exception:
                logger.error("graph_rebuild_failed", attempt=attempt + 1, exc_info=True)
                if attempt == 0:
                    await asyncio.sleep(30)

    async def _refresh_registry(self) -> None:
        """Scan for new plugins/skills and integrate them into the live registry.

        Called automatically before each AgentLoop operation (on_input / chat).
        Returns immediately when nothing new is found (fast path).
        """
        if self.agent_loop is None:
            return

        new_plugins = await self.plugin_loader.scan_new()
        new_skills = await self.skill_loader.scan_new()

        if not new_plugins and not new_skills:
            return

        all_new = {**new_plugins, **new_skills}

        # Merge into AgentLoop's registry (same dict reference)
        self.agent_loop._registry.update(all_new)

        # Update danger map
        self._danger_map.update(self.plugin_loader.danger_map)

        # Register new cron triggers
        if self.scheduler:
            self.scheduler.register_new_triggers(all_new)

        # Register new output plugins with SyncManager
        new_output_plugins = [m for m in new_plugins.values() if m.category == "output"]
        if new_output_plugins:
            self.sync_manager.register_output_plugins(
                new_output_plugins, self.runner, self.agent_loop.build_context
            )

        # Append new output skills (don't replace existing ones)
        new_output_skills = [m for m in new_skills.values() if m.category == "output"]
        for s in new_output_skills:
            self.sync_manager._output_skills.append(s)

        self.runtime_config.rebuild_enabled(self.agent_loop._registry, self.credential_store)

        logger.info(
            "registry_refreshed",
            new_plugins=list(new_plugins.keys()),
            new_skills=list(new_skills.keys()),
        )

    async def shutdown(self) -> None:
        """Stop scheduler and clean up resources."""
        if self.scheduler:
            self.scheduler.stop()
        # Cancel background tasks and await them to allow cleanup to run
        for attr in ("_reindex_task", "_graph_rebuild_task"):
            task = getattr(self, attr, None)
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        # Close databases
        await self.graph_store.close()
        if self.embedder.enabled:
            await self.vector_store.close()
        # Phase Audit Batch 2 — drain & stop the relay before closing the
        # outbox so we don't leave a polling task pointing at a closed DB.
        if self.audit_relay is not None:
            await self.audit_relay.stop()
        if self.audit_outbox is not None:
            await self.audit_outbox.close()
        logger.info("gateway_shutdown")
