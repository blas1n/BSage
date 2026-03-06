"""CLI-based interfaces: approval via click."""

from __future__ import annotations

import click
import structlog

from bsage.core.safe_mode import ApprovalRequest

logger = structlog.get_logger(__name__)


class CLIApprovalInterface:
    """Interactive terminal approval via click.confirm.

    Implements the ApprovalInterface protocol expected by SafeModeGuard.
    """

    async def request_approval(self, request: ApprovalRequest) -> bool:
        """Prompt the user in the terminal and return their decision."""
        message = (
            f"\n[SafeMode] Dangerous skill execution requested:\n"
            f"  Skill:       {request.skill_name}\n"
            f"  Description: {request.description}\n"
            f"  Action:      {request.action_summary}\n"
        )

        click.echo(message)

        approved = click.confirm("Do you approve this action?", default=False)

        logger.info(
            "cli_approval_result",
            skill=request.skill_name,
            approved=approved,
        )

        return approved


