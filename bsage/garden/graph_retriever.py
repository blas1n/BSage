"""GraphRetriever — graph-based note retrieval for knowledge graph RAG."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from bsage.garden.graph_models import GraphEntity
    from bsage.garden.graph_store import GraphStore
    from bsage.garden.vault import Vault

logger = structlog.get_logger(__name__)


class GraphRetriever:
    """Retrieves vault notes by traversing the knowledge graph.

    Given a query, searches for matching entities in the graph,
    performs multi-hop BFS traversal, collects related note paths,
    and returns formatted context including relationship information.
    """

    def __init__(self, graph_store: GraphStore, vault: Vault) -> None:
        self._store = graph_store
        self._vault = vault

    async def retrieve(
        self,
        query: str,
        *,
        max_hops: int = 2,
        top_k: int = 10,
        max_chars: int = 50_000,
    ) -> str:
        """Retrieve graph context for a query.

        Args:
            query: Search query — entity names are extracted and matched.
            max_hops: Maximum BFS traversal depth.
            top_k: Maximum number of related notes to include.
            max_chars: Maximum total characters in the result.

        Returns:
            Formatted string with graph relationships and note contents.
        """
        # 1. Find matching entities from query words
        matched = await self._match_entities(query)
        if not matched:
            return ""

        # 2. Multi-hop traversal from each matched entity
        source_paths: dict[str, int] = {}  # path -> min depth
        graph_lines: list[str] = ["## Graph Context"]

        for entity in matched:
            neighbors = await self._store.query_neighbors(entity.id)
            graph_lines.append(f"\nEntity: **{entity.name}** ({entity.entity_type})")
            for rel, neighbor in neighbors:
                direction = "->" if rel.source_id == entity.id else "<-"
                graph_lines.append(
                    f"  {direction} {rel.rel_type} {direction} "
                    f"**{neighbor.name}** ({neighbor.entity_type})"
                )
                if neighbor.source_path:
                    source_paths.setdefault(neighbor.source_path, 1)

            # Deeper hops
            hops = await self._store.multi_hop_query(entity.id, max_hops=max_hops)
            for depth, hop_entity in hops:
                if hop_entity.source_path:
                    source_paths.setdefault(hop_entity.source_path, depth)

            # Include the matched entity's own source
            if entity.source_path:
                source_paths.setdefault(entity.source_path, 0)

        # 3. Read note contents (sorted by depth, limited to top_k)
        sorted_paths = sorted(source_paths.items(), key=lambda x: x[1])[:top_k]

        parts: list[str] = ["\n".join(graph_lines)]
        total = len(parts[0])

        if sorted_paths:
            parts.append("\n## Related Notes")
            total += len(parts[-1])

        for path, _depth in sorted_paths:
            if total >= max_chars:
                break
            try:
                abs_path = self._vault.resolve_path(path)
                content = await self._vault.read_note_content(abs_path)
                remaining = max_chars - total
                chunk = content[:remaining]
                parts.append(chunk)
                total += len(chunk)
            except (FileNotFoundError, OSError, UnicodeDecodeError):
                logger.debug("graph_retrieve_read_failed", path=path)

        logger.info(
            "graph_retrieve",
            query=query,
            matched=len(matched),
            notes=len(sorted_paths),
            total_chars=total,
        )
        return "\n---\n".join(parts)

    async def _match_entities(self, query: str, *, limit: int = 5) -> list[GraphEntity]:
        """Extract entity names from query and find matches in the graph."""
        # Strategy: try full query first, then individual words
        results: list[GraphEntity] = []
        seen_ids: set[str] = set()

        # Try full query as entity name
        full_matches = await self._store.search_entities(query, limit=limit)
        for e in full_matches:
            if e.id not in seen_ids:
                seen_ids.add(e.id)
                results.append(e)

        # Try individual words (skip short ones)
        words = [w.strip() for w in query.split() if len(w.strip()) >= 3]
        for word in words:
            if len(results) >= limit:
                break
            matches = await self._store.search_entities(word, limit=3)
            for e in matches:
                if e.id not in seen_ids:
                    seen_ids.add(e.id)
                    results.append(e)
                    if len(results) >= limit:
                        break

        return results[:limit]
