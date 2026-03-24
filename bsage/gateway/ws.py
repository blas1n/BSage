"""WebSocket endpoint for real-time events and SafeMode approval."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from bsvibe_auth import SupabaseAuthProvider

    from bsage.interface.ws_interface import WebSocketApprovalInterface

logger = structlog.get_logger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info("ws_connected", count=len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            with contextlib.suppress(ValueError):
                self._connections.remove(websocket)
        logger.info("ws_disconnected", count=len(self._connections))

    def has_connections(self) -> bool:
        """Return True if at least one WebSocket client is connected."""
        return len(self._connections) > 0

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients.

        Copies the connection list under the lock, then sends outside the lock
        so that slow clients don't block connect/disconnect/other broadcasts.
        """
        data = json.dumps(message)
        async with self._lock:
            snapshot = self._connections[:]

        dead: list[WebSocket] = []
        for conn in snapshot:
            try:
                await conn.send_text(data)
            except Exception:
                logger.warning("ws_send_failed")
                dead.append(conn)

        if dead:
            async with self._lock:
                for conn in dead:
                    with contextlib.suppress(ValueError):
                        self._connections.remove(conn)


manager = ConnectionManager()


async def _authenticate_ws(
    websocket: WebSocket,
    auth_provider: SupabaseAuthProvider,
) -> bool:
    """Authenticate a WebSocket connection.

    Waits up to 10 seconds for an ``{"type": "auth", "token": "..."}`` message.
    Returns ``True`` on success, closes the connection with code 4001 on failure.
    """
    try:
        data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        message = json.loads(data)
        if message.get("type") == "auth" and message.get("token"):
            await auth_provider.verify_token(message["token"])
            logger.info("ws_auth_success", method="first_message")
            return True
        logger.warning("ws_auth_failed", reason="first message was not auth")
    except TimeoutError:
        logger.warning("ws_auth_failed", reason="timeout")
    except Exception as exc:
        logger.warning("ws_auth_failed", reason="invalid token or message", error=str(exc))

    await websocket.close(code=4001, reason="Authentication failed")
    return False


def create_ws_routes(
    approval_interface: WebSocketApprovalInterface | None = None,
    auth_provider: SupabaseAuthProvider | None = None,
) -> APIRouter:
    """Create WebSocket routes.

    Args:
        approval_interface: If provided, ``approval_response`` messages are
            routed to this interface to resolve pending approval futures.
        auth_provider: If provided, WebSocket connections must authenticate
            via first-message token exchange before joining the broadcast pool.
    """
    ws_router = APIRouter()

    @ws_router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        # Accept the socket but don't add to broadcast pool yet
        await websocket.accept()

        # Authenticate before joining the broadcast pool
        if auth_provider is not None and not await _authenticate_ws(websocket, auth_provider):
            return

        # Now safe to add to the broadcast pool
        async with manager._lock:
            manager._connections.append(websocket)
        logger.info("ws_connected", count=len(manager._connections))

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    logger.warning("ws_invalid_json", data=data[:200])
                    err = json.dumps({"type": "error", "detail": "invalid JSON"})
                    await websocket.send_text(err)
                    continue
                msg_type = message.get("type")
                logger.info("ws_message_received", type=msg_type)

                if msg_type == "approval_response":
                    if approval_interface is not None:
                        approval_interface.handle_response(message)
                    else:
                        await websocket.send_text(
                            json.dumps(
                                {"type": "error", "detail": "no approval interface configured"}
                            )
                        )
                        continue

                await websocket.send_text(json.dumps({"type": "ack", "received": msg_type}))
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(websocket)

    return ws_router
