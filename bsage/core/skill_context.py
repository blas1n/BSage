"""SkillContext — the context object injected into every Skill execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog

from bsage.connectors.base import BaseConnector
from bsage.connectors.manager import ConnectorManager
from bsage.garden.writer import GardenWriter


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM chat clients (litellm, mock, etc.)."""

    async def chat(self, system: str, messages: list[dict]) -> str: ...


class ConnectorAccessor:
    """Callable wrapper around ConnectorManager.get for use in SkillContext."""

    def __init__(self, manager: ConnectorManager) -> None:
        self._manager = manager

    async def __call__(self, name: str) -> BaseConnector:
        """Fetch a connector by name. Raises ConnectorNotFoundError if missing."""
        return await self._manager.get(name)


@dataclass
class SkillContext:
    """Context object injected into every skill execution.

    Skills access the outside world exclusively through this object:
    - connector("name") — fetch a connected external service
    - garden.write_seed / write_garden / write_action — vault I/O
    - llm.chat — LLM API calls
    - config — skill-specific configuration
    - logger — structured logger
    """

    connector: ConnectorAccessor
    garden: GardenWriter
    llm: LLMClient
    config: dict[str, Any]
    logger: structlog.typing.FilteringBoundLogger | Any
    input_data: dict[str, Any] | None = field(default=None)
