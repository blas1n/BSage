"""Tests for bsage.interface.cli_interface — CLIApprovalInterface and CLINotification."""

from unittest.mock import patch

import pytest

from bsage.core.safe_mode import ApprovalRequest
from bsage.interface.cli_interface import CLIApprovalInterface, CLINotification


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


class TestCLINotification:
    """Test CLINotification terminal output."""

    @pytest.mark.asyncio
    async def test_send_echoes_message(self) -> None:
        notifier = CLINotification()
        with patch("bsage.interface.cli_interface.click.echo") as mock_echo:
            await notifier.send("Hello from BSage")

        mock_echo.assert_called_once_with("[BSage] Hello from BSage")

    @pytest.mark.asyncio
    async def test_send_warning_uses_yellow_prefix(self) -> None:
        notifier = CLINotification()
        with (
            patch("bsage.interface.cli_interface.click.echo") as mock_echo,
            patch("bsage.interface.cli_interface.click.style", return_value="[BSage WARNING]"),
        ):
            await notifier.send("Watch out!", level="warning")

        mock_echo.assert_called_once_with("[BSage WARNING] Watch out!")

    @pytest.mark.asyncio
    async def test_send_error_uses_red_prefix(self) -> None:
        notifier = CLINotification()
        with (
            patch("bsage.interface.cli_interface.click.echo") as mock_echo,
            patch("bsage.interface.cli_interface.click.style", return_value="[BSage ERROR]"),
        ):
            await notifier.send("Something broke!", level="error")

        mock_echo.assert_called_once_with("[BSage ERROR] Something broke!")

    @pytest.mark.asyncio
    async def test_implements_notification_interface(self) -> None:
        from bsage.core.notification import NotificationInterface

        notifier = CLINotification()
        assert isinstance(notifier, NotificationInterface)
