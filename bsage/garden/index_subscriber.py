"""IndexSubscriber — EventBus subscriber that indexes notes after vault writes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from bsage.core.events import Event
    from bsage.garden.retriever import VaultRetriever
    from bsage.garden.vault import Vault

logger = structlog.get_logger(__name__)


class IndexSubscriber:
    """Listens for SEED_WRITTEN / GARDEN_WRITTEN events and indexes notes.

    Follows the same ``EventSubscriber`` protocol as
    ``WebSocketEventBroadcaster``.
    """

    def __init__(self, retriever: VaultRetriever, vault: Vault) -> None:
        self._retriever = retriever
        self._vault = vault

    async def on_event(self, event: Event) -> None:
        """Handle an event from the EventBus."""
        from bsage.core.events import EventType

        if event.event_type not in (
            EventType.SEED_WRITTEN,
            EventType.GARDEN_WRITTEN,
        ):
            return

        path_str = event.payload.get("path", "")
        if not path_str:
            return

        abs_path = Path(path_str)
        try:
            rel_path = str(abs_path.relative_to(self._vault.root))
            content = await self._vault.read_note_content(abs_path)
            await self._retriever.index_note(rel_path, content)
        except Exception:
            logger.warning("index_on_write_failed", path=path_str, exc_info=True)
