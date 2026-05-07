"""WebSocket-based approval interface for the Gateway."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from bsage.core.safe_mode import ApprovalDeferred, ApprovalRequest

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 120.0


class WebSocketApprovalInterface:
    """Approval interface that sends requests over WebSocket and awaits responses.

    Implements the ApprovalInterface protocol expected by SafeModeGuard.
    Used only for synchronous plugin Safe Mode — canonicalization typed
    actions are persisted as ``pending_approval`` and reviewed via the
    pull-based queue, not this push-based round-trip.

    Protocol:
    - Sends a JSON message of type ``approval_request`` with a unique ``request_id``.
    - Waits for a JSON message of type ``approval_response`` with the matching
      ``request_id`` and an ``approved`` boolean field.

    Raises :class:`ApprovalDeferred` when no human decision is available
    (no clients connected, or response timeout). SafeModeGuard turns
    this into a clear "no approver online" error for the caller —
    which is correct for one-shot plugin runs that can't wait forever.
    Earlier behaviour silently rejected on these conditions, which
    auto-denied every dangerous run while the operator was offline.
    """

    def __init__(
        self,
        manager: Any,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._manager = manager
        self._timeout = timeout
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request_approval(self, request: ApprovalRequest) -> bool:
        """Send an approval request over WebSocket and wait for a response.

        Returns the approver's explicit ``True``/``False`` decision.
        Raises :class:`ApprovalDeferred` if no clients are connected or
        the response doesn't arrive within ``timeout`` seconds.
        """
        if not self._manager.has_connections():
            logger.warning("ws_approval_no_clients", skill=request.skill_name)
            raise ApprovalDeferred(f"no WebSocket clients connected for {request.skill_name!r}")

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future

        message: dict[str, Any] = {
            "type": "approval_request",
            "request_id": request_id,
            "skill_name": request.skill_name,
            "description": request.description,
            "action_summary": request.action_summary,
        }
        # Canonicalization approvals (Handoff §13 step 11): add action_*
        # fields so the frontend can render evidence with source-aware
        # styling and link to the action note.
        if request.action_path is not None:
            message["action_path"] = request.action_path
            message["action_kind"] = request.action_kind
            message["stability_score"] = request.stability_score
            message["risk_reasons"] = request.risk_reasons
            message["affected_paths"] = request.affected_paths
            if request.source_proposal is not None:
                message["source_proposal"] = request.source_proposal

        await self._manager.broadcast(message)
        logger.info(
            "ws_approval_requested",
            skill=request.skill_name,
            request_id=request_id,
        )

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except TimeoutError as exc:
            logger.warning(
                "ws_approval_timeout",
                skill=request.skill_name,
                request_id=request_id,
            )
            raise ApprovalDeferred(
                f"no approval response for {request.skill_name!r} within {self._timeout}s"
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    def handle_response(self, data: dict[str, Any]) -> None:
        """Process an incoming ``approval_response`` message from WebSocket.

        Resolves the corresponding pending future.
        """
        request_id = data.get("request_id", "")
        approved = bool(data.get("approved", False))

        future = self._pending.get(request_id)
        if future is None or future.done():
            logger.warning("ws_approval_response_unknown", request_id=request_id)
            return

        future.set_result(approved)
