"""Tests for bsage.interface.cli_interface — CLIApprovalInterface."""

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
        with patch("bsage.interface.cli_interface.click.confirm", return_value=True):
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
        with patch("bsage.interface.cli_interface.click.confirm", return_value=False):
            result = await interface.request_approval(request)
        assert result is False

    @pytest.mark.asyncio
    async def test_request_approval_echoes_details(self) -> None:
        interface = CLIApprovalInterface()
        request = ApprovalRequest(
            skill_name="test-skill",
            description="Test description",
            action_summary="[process] Test action",
        )
        with (
            patch("bsage.interface.cli_interface.click.echo") as mock_echo,
            patch("bsage.interface.cli_interface.click.confirm", return_value=True),
        ):
            await interface.request_approval(request)

        echo_text = mock_echo.call_args[0][0]
        assert "test-skill" in echo_text
        assert "Test description" in echo_text
