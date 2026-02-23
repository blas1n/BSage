"""FastAPI dependency injection for the Gateway."""

from __future__ import annotations

import structlog

from bsage.core.agent_loop import AgentLoop
from bsage.core.config import Settings
from bsage.core.credential_store import CredentialStore
from bsage.core.llm import LiteLLMClient
from bsage.core.prompt_registry import PromptRegistry
from bsage.core.runtime_config import RuntimeConfig
from bsage.core.safe_mode import SafeModeGuard
from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillLoader
from bsage.core.skill_runner import SkillRunner
from bsage.garden.sync import SyncManager
from bsage.garden.vault import Vault
from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)


class AppState:
    """Holds all initialized core components for the Gateway."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Runtime config (mutable, shared reference, persisted to JSON)
        # Store in credentials_dir (gitignored) — NOT vault_path (may be synced)
        persist_path = settings.credentials_dir / "runtime_config.json"
        self.runtime_config = RuntimeConfig.from_settings(settings, persist_path=persist_path)

        # Sync manager (backends registered later by OutputSkills)
        self.sync_manager = SyncManager()

        # Garden layer
        self.vault = Vault(settings.vault_path)
        self.garden_writer = GardenWriter(self.vault, sync_manager=self.sync_manager)

        # Credentials
        self.credential_store = CredentialStore(settings.credentials_dir)

        # LLM (reads from RuntimeConfig per-call)
        self.llm_client = LiteLLMClient(runtime_config=self.runtime_config)

        # SafeMode (reads from RuntimeConfig per-call)
        self.safe_mode_guard = SafeModeGuard(
            runtime_config=self.runtime_config,
            interface=None,
        )

        # Prompts
        self.prompt_registry = PromptRegistry(settings.prompts_dir)

        # Skills
        self.skill_loader = SkillLoader(settings.skills_dir)
        self.skill_runner = SkillRunner(
            skills_dir=settings.skills_dir,
            credential_store=self.credential_store,
            prompt_registry=self.prompt_registry,
        )

        # Agent loop (registry populated after load_all)
        self.agent_loop: AgentLoop | None = None
        self.scheduler: Scheduler | None = None

    async def initialize(self) -> None:
        """Load skills, create AgentLoop, register triggers, start scheduler."""
        registry = await self.skill_loader.load_all()
        logger.info("skills_loaded", count=len(registry))

        self.agent_loop = AgentLoop(
            registry=registry,
            skill_runner=self.skill_runner,
            safe_mode_guard=self.safe_mode_guard,
            garden_writer=self.garden_writer,
            llm_client=self.llm_client,
            prompt_registry=self.prompt_registry,
        )

        self.scheduler = Scheduler(
            agent_loop=self.agent_loop,
            skill_runner=self.skill_runner,
            safe_mode_guard=self.safe_mode_guard,
        )
        self.scheduler.register_triggers(registry)
        self.scheduler.start()
        logger.info("gateway_initialized")

    async def shutdown(self) -> None:
        """Stop scheduler and clean up resources."""
        if self.scheduler:
            self.scheduler.stop()
        logger.info("gateway_shutdown")
