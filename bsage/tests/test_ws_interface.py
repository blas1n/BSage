"""Tests for the WebSocket-based approval interface."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bsage.core.safe_mode import ApprovalRequest
from bsage.interface.ws_interface import WebSocketApprovalInterface


def _make_request(name: str = "dangerous-plugin") -> ApprovalRequest:
    return ApprovalRequest(
        skill_name=name,
        description="A dangerous plugin",
        action_summary=f"Execute '{name}'",
    )


@pytest.fixture()
def mock_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.has_connections = MagicMock(return_value=True)
    mgr.broadcast = AsyncMock()
    return mgr


@pytest.fixture()
def interface(mock_manager: MagicMock) -> WebSocketApprovalInterface:
    return WebSocketApprovalInterface(manager=mock_manager, timeout=2.0)


async def test_request_approval_returns_true_when_approved(
    interface: WebSocketApprovalInterface,
    mock_manager: MagicMock,
) -> None:
    """Approval resolves True when a matching response comes back."""
    request = _make_request()

    async def _resolve_after_broadcast(*_args: object, **_kwargs: object) -> None:
        # After broadcast, resolve the single pending future
        await asyncio.sleep(0.01)
        for future in interface._pending.values():
            future.set_result(True)

    mock_manager.broadcast = AsyncMock(side_effect=_resolve_after_broadcast)

    result = await interface.request_approval(request)
    assert result is True


async def test_request_approval_returns_false_when_rejected(
    interface: WebSocketApprovalInterface,
    mock_manager: MagicMock,
) -> None:
    """Approval resolves False when user rejects."""
    request = _make_request()

    async def _resolve_reject(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.01)
        for future in interface._pending.values():
            future.set_result(False)

    mock_manager.broadcast = AsyncMock(side_effect=_resolve_reject)

    result = await interface.request_approval(request)
    assert result is False


async def test_request_approval_returns_false_on_timeout(
    mock_manager: MagicMock,
) -> None:
    """Approval returns False when no response within timeout."""
    iface = WebSocketApprovalInterface(manager=mock_manager, timeout=0.05)
    result = await iface.request_approval(_make_request())
    assert result is False
    assert len(iface._pending) == 0  # cleaned up


async def test_request_approval_returns_false_when_no_clients(
    mock_manager: MagicMock,
) -> None:
    """Approval returns False immediately when no WS clients are connected."""
    mock_manager.has_connections.return_value = False
    iface = WebSocketApprovalInterface(manager=mock_manager)
    result = await iface.request_approval(_make_request())
    assert result is False
    mock_manager.broadcast.assert_not_awaited()


async def test_handle_response_resolves_pending_future(
    interface: WebSocketApprovalInterface,
    mock_manager: MagicMock,
) -> None:
    """handle_response resolves the correct pending future."""
    request = _make_request()

    # Start request_approval in background, capture the request_id
    async def _capture_and_respond(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.01)
        # Find the pending request_id and resolve it
        for req_id in list(interface._pending):
            interface.handle_response({"request_id": req_id, "approved": True})

    mock_manager.broadcast = AsyncMock(side_effect=_capture_and_respond)

    result = await interface.request_approval(request)
    assert result is True


async def test_handle_response_unknown_request_id(
    interface: WebSocketApprovalInterface,
) -> None:
    """handle_response does not crash on unknown request_id."""
    interface.handle_response({"request_id": "nonexistent", "approved": True})
    # No exception raised, no pending futures affected


async def test_broadcast_message_format(
    interface: WebSocketApprovalInterface,
    mock_manager: MagicMock,
) -> None:
    """Verify broadcast message has the correct structure."""
    request = _make_request("test-plugin")

    # Use a short timeout so we don't wait long
    interface._timeout = 0.05
    await interface.request_approval(request)

    mock_manager.broadcast.assert_awaited_once()
    msg = mock_manager.broadcast.call_args[0][0]
    assert msg["type"] == "approval_request"
    assert msg["skill_name"] == "test-plugin"
    assert msg["description"] == "A dangerous plugin"
    assert "request_id" in msg
    assert "action_summary" in msg
