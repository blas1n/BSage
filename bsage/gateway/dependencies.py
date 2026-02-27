"""FastAPI dependency injection for the Gateway."""

from __future__ import annotations

import asyncio

import structlog

from bsage.core.agent_loop import AgentLoop
from bsage.core.config import Settings
from bsage.core.credential_store import CredentialStore
from bsage.core.danger_analyzer import DangerAnalyzer
from bsage.core.events import EventBus
from bsage.core.llm import LiteLLMClient
from bsage.core.notification import NotificationRouter
from bsage.core.plugin_loader import PluginLoader
from bsage.core.plugin_runner import PluginRunner
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runner import Runner
from bsage.core.runtime_config import RuntimeConfig
from bsage.core.safe_mode import SafeModeGuard
from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillLoader
from bsage.core.skill_runner import SkillRunner
from bsage.garden.embeddings import EmbeddingClient
from bsage.garden.retriever import VaultRetriever
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.garden.vector_store import VectorStore
from bsage.garden.writer import GardenWriter
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
        self.sync_manager = SyncManager()

        # Garden layer
        self.vault = Vault(settings.vault_path)
        self.garden_writer = GardenWriter(
            self.vault, sync_manager=self.sync_manager, event_bus=self.event_bus
        )

        # Credentials
        self.credential_store = CredentialStore(settings.credentials_dir)

        # LLM (reads from RuntimeConfig per-call)
        self.llm_client = LiteLLMClient(runtime_config=self.runtime_config)

        # danger_map populated in initialize() after plugin load_all()
        self._danger_map: dict[str, bool] = {}

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

        # RAG components (optional — active when embedding_model is configured)
        self.embedding_client: EmbeddingClient | None = None
        self.vector_store: VectorStore | None = None

        if self.runtime_config.embedding_model:
            self.embedding_client = EmbeddingClient(runtime_config=self.runtime_config)
            rag_path = settings.rag_index_path or (settings.vault_path / ".rag" / "index.db")
            self.vector_store = VectorStore(rag_path)

        self.retriever = VaultRetriever(
            vault=self.vault,
            vector_store=self.vector_store,
            embedding_client=self.embedding_client,
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
        self.scheduler: Scheduler | None = None

    @property
    def danger_map(self) -> dict[str, bool]:
        """Public accessor for the danger classification map."""
        return self._danger_map

    async def initialize(self) -> None:
        """Load plugins and skills, create AgentLoop, register triggers, start scheduler."""
        # Initialize vector store for RAG
        if self.vector_store:
            await self.vector_store.initialize()

        # Subscribe index subscriber to EventBus for write-time indexing
        if self.retriever.rag_available:
            from bsage.garden.index_subscriber import IndexSubscriber

            index_sub = IndexSubscriber(self.retriever, self.vault)
            self.event_bus.subscribe(index_sub)

        # Background reindex to pick up manual vault edits (Obsidian, etc.)
        if self.retriever.rag_available:
            self._reindex_task = asyncio.create_task(self._background_reindex())

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

        notification_router = NotificationRouter()

        self.agent_loop = AgentLoop(
            registry=registry,
            runner=self.runner,
            safe_mode_guard=self.safe_mode_guard,
            garden_writer=self.garden_writer,
            llm_client=self.llm_client,
            prompt_registry=self.prompt_registry,
            notification=notification_router,
            event_bus=self.event_bus,
        )

        notification_router.setup(
            registry=registry,
            runner=self.runner,
            context_builder=self.agent_loop.build_context,
        )

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
        self.scheduler.start()
        logger.info("gateway_initialized")

    async def _background_reindex(self) -> None:
        """Reconcile index with vault contents on startup.

        Runs in the background so it doesn't block server startup.
        Content-hash dedup ensures only new/changed notes are re-embedded.
        """
        try:
            count = await self.retriever.reindex_all()
            logger.info("startup_reindex_complete", indexed=count)
        except Exception:
            logger.warning("startup_reindex_failed", exc_info=True)

    async def shutdown(self) -> None:
        """Stop scheduler and clean up resources."""
        if self.scheduler:
            self.scheduler.stop()
        # Cancel background reindex if still running
        task = getattr(self, "_reindex_task", None)
        if task and not task.done():
            task.cancel()
        if self.vector_store:
            await self.vector_store.close()
        logger.info("gateway_shutdown")
