"""CanonicalizationIndexSubscriber — keeps the canon index fresh from events.

Per Class_Diagram §10.2 — mirrors the existing
``bsage.garden.index_subscriber.IndexSubscriber`` pattern. Subscribes to
the EventBus and calls ``CanonicalizationIndex.invalidate(path)`` on
every event that touches a canon path.

Sources of truth:
- ``CANONICALIZATION_*`` events emitted by the service after every
  successful state transition (Handoff §14)
- ``NOTE_UPDATED`` events from the ``canon-watcher`` plugin (slice 6)
  when external tools (Obsidian, git) edit canon notes outside the API

Defense in depth: the service ALSO calls ``invalidate()`` directly after
each write, so the subscriber's job is mostly to catch external writes.
Re-invalidating an already-fresh path is a no-op (idempotent reload).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from bsage.core.events import Event
    from bsage.garden.canonicalization.index import CanonicalizationIndex

logger = structlog.get_logger(__name__)


_CANON_PATH_PREFIXES: tuple[str, ...] = (
    "concepts/active/",
    "concepts/merged/",
    "concepts/deprecated/",
    "proposals/",
    "actions/",
    "decisions/",
)


class CanonicalizationIndexSubscriber:
    """EventSubscriber that invalidates the canon index on relevant events.

    Listens to:
    - All ``CANONICALIZATION_*`` events (service-emitted)
    - ``NOTE_UPDATED`` / ``NOTE_DELETED`` events whose path is under a
      canon root (so canon-watcher / external edits are picked up)
    """

    def __init__(self, index: CanonicalizationIndex) -> None:
        self._index = index

    async def on_event(self, event: Event) -> None:
        from bsage.core.events import EventType

        name = event.event_type.value
        payload = event.payload or {}

        # Canonicalization domain events — extract every canon path the
        # event touched and invalidate each.
        if name.startswith("canonicalization_"):
            for path in self._extract_canon_paths(payload):
                await self._safe_invalidate(path)
            return

        # External vault edits — only canon-rooted paths matter to us.
        if event.event_type in (EventType.NOTE_UPDATED, EventType.NOTE_DELETED):
            path = payload.get("path")
            if isinstance(path, str) and self._is_canon_path(path):
                await self._safe_invalidate(path)

    @staticmethod
    def _extract_canon_paths(payload: dict[str, Any]) -> list[str]:
        """Pull every canon-touching path out of an event payload."""
        out: list[str] = []
        # Single-path keys
        for key in ("path", "action_path"):
            v = payload.get(key)
            if isinstance(v, str):
                out.append(v)
        # List keys (action_applied carries affected_paths)
        for key in ("affected_paths",):
            v = payload.get(key)
            if isinstance(v, list):
                out.extend(p for p in v if isinstance(p, str))
        # Dedupe while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for p in out:
            if p not in seen and CanonicalizationIndexSubscriber._is_canon_path(p):
                seen.add(p)
                unique.append(p)
        return unique

    @staticmethod
    def _is_canon_path(path: str) -> bool:
        return path.startswith(_CANON_PATH_PREFIXES)

    async def _safe_invalidate(self, path: str) -> None:
        try:
            await self._index.invalidate(path)
        except Exception as exc:  # noqa: BLE001 — never let a subscriber crash the bus
            logger.warning(
                "canon_index_subscriber_invalidate_failed",
                path=path,
                error=str(exc),
            )
