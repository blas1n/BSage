"""Tests for bsage.gateway.event_broadcaster — WebSocketEventBroadcaster."""

from unittest.mock import AsyncMock, MagicMock

from bsage.core.events import Event, EventType
from bsage.gateway.event_broadcaster import WebSocketEventBroadcaster


class TestWebSocketEventBroadcaster:
    """Test WebSocket event broadcasting."""

    async def test_broadcasts_event_to_manager(self) -> None:
        manager = MagicMock()
        manager.has_connections.return_value = True
        manager.broadcast = AsyncMock()

        broadcaster = WebSocketEventBroadcaster(manager=manager)
        event = Event(
            event_type=EventType.PLUGIN_RUN_START,
            payload={"name": "telegram-input"},
            correlation_id="test-123",
        )

        await broadcaster.on_event(event)

        manager.broadcast.assert_awaited_once()
        msg = manager.broadcast.call_args[0][0]
        assert msg["type"] == "event"
        assert msg["event_type"] == "plugin_run_start"
        assert msg["correlation_id"] == "test-123"
        assert msg["payload"]["name"] == "telegram-input"

    async def test_skips_broadcast_when_no_connections(self) -> None:
        manager = MagicMock()
        manager.has_connections.return_value = False
        manager.broadcast = AsyncMock()

        broadcaster = WebSocketEventBroadcaster(manager=manager)
        event = Event(event_type=EventType.SEED_WRITTEN)

        await broadcaster.on_event(event)

        manager.broadcast.assert_not_awaited()

    async def test_broadcast_payload_format(self) -> None:
        manager = MagicMock()
        manager.has_connections.return_value = True
        manager.broadcast = AsyncMock()

        broadcaster = WebSocketEventBroadcaster(manager=manager)
        event = Event(
            event_type=EventType.SKILL_GATHER_COMPLETE,
            payload={"name": "weekly-digest", "context_length": 5000},
        )

        await broadcaster.on_event(event)

        msg = manager.broadcast.call_args[0][0]
        assert msg["type"] == "event"
        assert msg["event_type"] == "skill_gather_complete"
        assert msg["payload"]["context_length"] == 5000
        assert "timestamp" in msg
