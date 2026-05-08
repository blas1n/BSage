"""CLI-based interfaces: SafeMode approval via stdin prompt.

Uses stdlib ``input``/``print`` (no click dependency) so the BSage
codebase can drop click entirely after the Phase 4 CLI migration.
"""

from __future__ import annotations

import structlog

from bsage.core.safe_mode import ApprovalRequest

logger = structlog.get_logger(__name__)


class CLIApprovalInterface:
    """Interactive terminal approval via stdin y/n prompt.

    Implements the ApprovalInterface protocol expected by SafeModeGuard.
    Defaults to deny — empty input, EOF, and any non-affirmative answer
    all return ``False`` so an unattended terminal never silently
    approves a dangerous action.
    """

    async def request_approval(self, request: ApprovalRequest) -> bool:
        """Prompt the user in the terminal and return their decision."""
        message = (
            f"\n[SafeMode] Dangerous skill execution requested:\n"
            f"  Skill:       {request.skill_name}\n"
            f"  Description: {request.description}\n"
            f"  Action:      {request.action_summary}\n"
        )
        print(message)  # noqa: T201 — interactive prompt, not logging

        try:
            answer = input("Do you approve this action? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""

        approved = answer in {"y", "yes"}

        logger.info(
            "cli_approval_result",
            skill=request.skill_name,
            approved=approved,
        )

        return approved
