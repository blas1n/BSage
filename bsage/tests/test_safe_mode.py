"""Tests for bsage.core.safe_mode — SafeModeGuard and ApprovalRequest."""

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from bsage.core.exceptions import SafeModeError
from bsage.core.runtime_config import RuntimeConfig
from bsage.core.safe_mode import ApprovalRequest, SafeModeGuard


@dataclass
class _FakeSkillMeta:
    """Minimal skill metadata for testing SafeModeGuard."""

    name: str
    description: str
    category: str
    is_dangerous: bool


def _make_config(safe_mode: bool = True) -> RuntimeConfig:
    return RuntimeConfig(
        llm_model="test-model",
        llm_api_key="",
        llm_api_base=None,
        safe_mode=safe_mode,
    )


class TestApprovalRequest:
    """Tests for the ApprovalRequest dataclass."""

    def test_approval_request_fields(self) -> None:
        request = ApprovalRequest(
            skill_name="email-sender",
            description="Send emails via SMTP",
            action_summary="Send 3 emails to contacts",
            connector_name="smtp-connector",
        )
        assert request.skill_name == "email-sender"
        assert request.description == "Send emails via SMTP"
        assert request.action_summary == "Send 3 emails to contacts"
        assert request.connector_name == "smtp-connector"

    def test_approval_request_connector_name_defaults_to_none(self) -> None:
        request = ApprovalRequest(
            skill_name="garden-writer",
            description="Write garden notes",
            action_summary="Write 5 notes",
        )
        assert request.connector_name is None


class TestSafeModeGuard:
    """Tests for SafeModeGuard approval logic."""

    async def test_non_dangerous_skill_passes(self) -> None:
        mock_interface = AsyncMock()
        mock_interface.request_approval = AsyncMock(return_value=False)

        guard = SafeModeGuard(runtime_config=_make_config(True), interface=mock_interface)
        skill = _FakeSkillMeta(
            name="garden-writer",
            description="Write garden notes",
            category="process",
            is_dangerous=False,
        )

        result = await guard.check(skill)
        assert result is True
        mock_interface.request_approval.assert_not_called()

    async def test_dangerous_skill_approved(self) -> None:
        mock_interface = AsyncMock()
        mock_interface.request_approval = AsyncMock(return_value=True)

        guard = SafeModeGuard(runtime_config=_make_config(True), interface=mock_interface)
        skill = _FakeSkillMeta(
            name="email-sender",
            description="Send emails",
            category="output",
            is_dangerous=True,
        )

        result = await guard.check(skill)
        assert result is True
        mock_interface.request_approval.assert_called_once()

    async def test_dangerous_skill_rejected(self) -> None:
        mock_interface = AsyncMock()
        mock_interface.request_approval = AsyncMock(return_value=False)

        guard = SafeModeGuard(runtime_config=_make_config(True), interface=mock_interface)
        skill = _FakeSkillMeta(
            name="email-sender",
            description="Send emails",
            category="output",
            is_dangerous=True,
        )

        result = await guard.check(skill)
        assert result is False
        mock_interface.request_approval.assert_called_once()

    async def test_safe_mode_disabled_always_passes(self) -> None:
        mock_interface = AsyncMock()
        mock_interface.request_approval = AsyncMock(return_value=False)

        guard = SafeModeGuard(runtime_config=_make_config(False), interface=mock_interface)
        dangerous_skill = _FakeSkillMeta(
            name="email-sender",
            description="Send emails",
            category="output",
            is_dangerous=True,
        )

        result = await guard.check(dangerous_skill)
        assert result is True
        mock_interface.request_approval.assert_not_called()

    async def test_dangerous_skill_approval_request_contains_skill_info(self) -> None:
        mock_interface = AsyncMock()
        mock_interface.request_approval = AsyncMock(return_value=True)

        guard = SafeModeGuard(runtime_config=_make_config(True), interface=mock_interface)
        skill = _FakeSkillMeta(
            name="telegram-sender",
            description="Send Telegram messages",
            category="output",
            is_dangerous=True,
        )

        await guard.check(skill)

        call_args = mock_interface.request_approval.call_args
        request: ApprovalRequest = call_args[0][0]
        assert request.skill_name == "telegram-sender"
        assert request.description == "Send Telegram messages"

    async def test_check_with_none_interface_and_dangerous_skill(self) -> None:
        guard = SafeModeGuard(runtime_config=_make_config(True), interface=None)
        skill = _FakeSkillMeta(
            name="email-sender",
            description="Send emails",
            category="output",
            is_dangerous=True,
        )

        with pytest.raises(SafeModeError):
            await guard.check(skill)

    async def test_runtime_toggle_safe_mode(self) -> None:
        """Changing safe_mode at runtime should take effect immediately."""
        config = _make_config(True)
        guard = SafeModeGuard(runtime_config=config, interface=None)

        safe_skill = _FakeSkillMeta(
            name="email-sender",
            description="Send emails",
            category="output",
            is_dangerous=True,
        )

        # safe_mode=True, no interface → raises
        with pytest.raises(SafeModeError):
            await guard.check(safe_skill)

        # Disable safe_mode at runtime → passes
        config.update_safe_mode(False)
        result = await guard.check(safe_skill)
        assert result is True
