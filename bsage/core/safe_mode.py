"""SafeModeGuard — approval gate for dangerous skill execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from bsage.core.exceptions import SafeModeError

if TYPE_CHECKING:
    from bsage.core.runtime_config import RuntimeConfig

logger = structlog.get_logger(__name__)


@dataclass
class ApprovalRequest:
    """Data passed to an ApprovalInterface when requesting user consent.

    Skill approvals (legacy) populate ``skill_name`` / ``description`` /
    ``action_summary``. Canonicalization approvals (Handoff §13 step 11)
    additionally populate the action_* fields so the frontend can render
    evidence with source-aware styling.
    """

    skill_name: str
    description: str
    action_summary: str
    action_path: str | None = None
    action_kind: str | None = None
    stability_score: float | None = None
    risk_reasons: list[dict] = field(default_factory=list)
    affected_paths: list[str] = field(default_factory=list)
    source_proposal: str | None = None


@runtime_checkable
class ApprovalInterface(Protocol):
    """Protocol that any approval UI (CLI, web, etc.) must implement."""

    async def request_approval(self, request: ApprovalRequest) -> bool: ...


class SafeModeGuard:
    """Gate that blocks dangerous skills unless the user explicitly approves.

    Reads the safe_mode flag from RuntimeConfig on every check, so it
    reflects runtime changes immediately without restart.
    """

    def __init__(
        self,
        runtime_config: RuntimeConfig,
        interface: ApprovalInterface | None,
        danger_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._config = runtime_config
        self._interface = interface
        self._danger_fn: Callable[[str], bool] = danger_fn or (lambda _: False)

    async def check(self, skill_meta: Any) -> bool:
        """Return True if the skill is allowed to run.

        * Non-dangerous skills always pass.
        * When safe mode is disabled, all skills pass.
        * Dangerous skills require approval via the interface.
        * If no interface is configured for a dangerous skill, raises SafeModeError.
        """
        if not self._config.safe_mode:
            logger.info("safe_mode_disabled", skill=skill_meta.name)
            return True

        if not self._danger_fn(skill_meta.name):
            logger.debug("safe_mode_pass", skill=skill_meta.name, dangerous=False)
            return True

        # Dangerous skill — need approval
        if self._interface is None:
            logger.error(
                "safe_mode_no_interface",
                skill=skill_meta.name,
            )
            raise SafeModeError(
                f"No approval interface configured for dangerous skill '{skill_meta.name}'"
            )

        request = ApprovalRequest(
            skill_name=skill_meta.name,
            description=skill_meta.description,
            action_summary=f"Execute dangerous skill '{skill_meta.name}' ({skill_meta.category})",
        )

        approved = await self._interface.request_approval(request)

        if approved:
            logger.info("safe_mode_approved", skill=skill_meta.name)
        else:
            logger.warning("safe_mode_rejected", skill=skill_meta.name)

        return approved
