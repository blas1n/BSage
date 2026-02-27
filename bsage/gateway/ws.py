"""WebSocket endpoint for real-time events and SafeMode approval."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from bsage.interface.ws_interface import WebSocketApprovalInterface

logger = structlog.get_logger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("ws_connected", count=len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.remove(websocket)
        logger.info("ws_disconnected", count=len(self._connections))

    def has_connections(self) -> bool:
        """Return True if at least one WebSocket client is connected."""
        return len(self._connections) > 0

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients."""
        data = json.dumps(message)
        for conn in self._connections:
            try:
                await conn.send_text(data)
            except Exception:
                logger.warning("ws_send_failed")


manager = ConnectionManager()


def create_ws_routes(
    approval_interface: WebSocketApprovalInterface | None = None,
) -> APIRouter:
    """Create WebSocket routes.

    Args:
        approval_interface: If provided, ``approval_response`` messages are
            routed to this interface to resolve pending approval futures.
    """
    ws_router = APIRouter()

    @ws_router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                msg_type = message.get("type")
                logger.info("ws_message_received", type=msg_type)

                if msg_type == "approval_response" and approval_interface is not None:
                    approval_interface.handle_response(message)

                await websocket.send_text(json.dumps({"type": "ack", "received": msg_type}))
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return ws_router
