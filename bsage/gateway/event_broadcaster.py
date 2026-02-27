"""WebSocketEventBroadcaster — bridges EventBus to WebSocket ConnectionManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bsage.core.events import Event
    from bsage.gateway.ws import ConnectionManager


class WebSocketEventBroadcaster:
    """Subscribes to EventBus and broadcasts events to all WebSocket clients.

    Implements the ``EventSubscriber`` protocol.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def on_event(self, event: Event) -> None:
        """Broadcast an event to all connected WebSocket clients."""
        if not self._manager.has_connections():
            return
        await self._manager.broadcast(event.to_dict())
