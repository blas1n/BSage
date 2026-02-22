"""WebSocket endpoint for real-time events and SafeMode approval."""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients."""
        data = json.dumps(message)
        for conn in self._connections:
            try:
                await conn.send_text(data)
            except Exception:
                logger.warning("ws_send_failed")


manager = ConnectionManager()


def create_ws_routes() -> APIRouter:
    """Create WebSocket routes."""
    ws_router = APIRouter()

    @ws_router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                logger.info("ws_message_received", type=message.get("type"))
                await websocket.send_text(
                    json.dumps({"type": "ack", "received": message.get("type")})
                )
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return ws_router
