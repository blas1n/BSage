"""SkillContext — the context object injected into every Skill execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import structlog

from bsage.core.notification import NotificationInterface
from bsage.garden.writer import GardenWriter


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM chat clients (litellm, mock, etc.)."""

    async def chat(self, system: str, messages: list[dict]) -> str: ...


@dataclass
class SkillContext:
    """Context object injected into every skill execution.

    Skills access the outside world exclusively through this object:
    - credentials — auto-injected dict of resolved credentials for this skill
    - garden.write_seed / write_garden / write_action — vault I/O
    - llm.chat — LLM API calls
    - config — skill-specific configuration
    - logger — structured logger
    - notify.send() — send notifications to the user
    """

    garden: GardenWriter
    llm: LLMClient
    config: dict[str, Any]
    logger: structlog.typing.FilteringBoundLogger | Any
    credentials: dict[str, Any] = field(default_factory=dict)
    input_data: dict[str, Any] | None = field(default=None)
    notify: NotificationInterface | None = field(default=None)
