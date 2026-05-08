"""Tests for bsage.interface.cli_interface — CLIApprovalInterface.

The approval interface uses stdlib ``input`` for the y/n prompt (no
click dependency) so the rest of the BSage codebase can drop click
entirely (TASK-007).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bsage.core.safe_mode import ApprovalRequest
from bsage.interface.cli_interface import CLIApprovalInterface


class TestCLIApprovalInterface:
    """Test CLIApprovalInterface approval flow."""

    @pytest.mark.asyncio
    async def test_request_approval_approved(self) -> None:
        interface = CLIApprovalInterface()
        request = ApprovalRequest(
            skill_name="email-sender",
            description="Send an email",
            action_summary="[process] Send an email",
        )
        with patch("builtins.input", return_value="y"):
            result = await interface.request_approval(request)
        assert result is True

    @pytest.mark.asyncio
    async def test_request_approval_denied(self) -> None:
        interface = CLIApprovalInterface()
        request = ApprovalRequest(
            skill_name="email-sender",
            description="Send an email",
            action_summary="[process] Send an email",
        )
        with patch("builtins.input", return_value="n"):
            result = await interface.request_approval(request)
        assert result is False

    @pytest.mark.asyncio
    async def test_request_approval_default_no_on_empty(self) -> None:
        interface = CLIApprovalInterface()
        request = ApprovalRequest(
            skill_name="email-sender",
            description="Send an email",
            action_summary="[process] Send an email",
        )
        # Empty input == press-enter == default no.
        with patch("builtins.input", return_value=""):
            result = await interface.request_approval(request)
        assert result is False

    @pytest.mark.asyncio
    async def test_request_approval_echoes_details(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        interface = CLIApprovalInterface()
        request = ApprovalRequest(
            skill_name="test-skill",
            description="Test description",
            action_summary="[process] Test action",
        )
        with patch("builtins.input", return_value="y"):
            await interface.request_approval(request)
        captured = capsys.readouterr()
        assert "test-skill" in captured.out
        assert "Test description" in captured.out
        assert "[process] Test action" in captured.out

    @pytest.mark.asyncio
    async def test_request_approval_eof_treated_as_deny(self) -> None:
        """If stdin is closed (EOFError), default to deny — never silently approve."""
        interface = CLIApprovalInterface()
        request = ApprovalRequest(
            skill_name="email-sender",
            description="Send an email",
            action_summary="[process] Send an email",
        )
        with patch("builtins.input", side_effect=EOFError):
            result = await interface.request_approval(request)
        assert result is False
