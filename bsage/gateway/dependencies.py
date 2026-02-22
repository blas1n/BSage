"""FastAPI dependency injection for the Gateway."""

from __future__ import annotations

import structlog

from bsage.connectors.manager import ConnectorManager
from bsage.core.agent_loop import AgentLoop
from bsage.core.config import Settings
from bsage.core.llm import LiteLLMClient
from bsage.core.safe_mode import SafeModeGuard
from bsage.core.scheduler import Scheduler
from bsage.core.skill_loader import SkillLoader
from bsage.core.skill_runner import SkillRunner
from bsage.garden.vault import Vault
from bsage.garden.writer import GardenWriter

logger = structlog.get_logger(__name__)


class AppState:
    """Holds all initialized core components for the Gateway."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Garden layer
        self.vault = Vault(settings.vault_path)
        self.garden_writer = GardenWriter(self.vault)

        # Connectors
        self.connector_manager = ConnectorManager()

        # LLM
        self.llm_client = LiteLLMClient(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
        )

        # SafeMode
        self.safe_mode_guard = SafeModeGuard(enabled=settings.safe_mode, interface=None)

        # Skills
        self.skill_loader = SkillLoader(settings.skills_dir)
        self.skill_runner = SkillRunner(skills_dir=settings.skills_dir)

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
            connector_manager=self.connector_manager,
        )

        self.scheduler = Scheduler(
            agent_loop=self.agent_loop,
            skill_runner=self.skill_runner,
        )
        self.scheduler.register_triggers(registry)
        self.scheduler.start()
        logger.info("gateway_initialized")

    async def shutdown(self) -> None:
        """Stop scheduler and clean up resources."""
        if self.scheduler:
            self.scheduler.stop()
        logger.info("gateway_shutdown")
