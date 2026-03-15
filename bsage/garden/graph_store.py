"""GraphStore — async SQLite-backed knowledge graph storage."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
import structlog

from bsage.garden.graph_models import GraphEntity, GraphRelationship, ProvenanceRecord

if TYPE_CHECKING:
    from bsage.garden.graph_extractor import GraphExtractor
    from bsage.garden.vault import Vault

logger = structlog.get_logger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_dedup
    ON entities (name_normalized, entity_type);

CREATE INDEX IF NOT EXISTS idx_entities_source
    ON entities (source_path);

CREATE INDEX IF NOT EXISTS idx_entities_type
    ON entities (entity_type);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (source_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships (source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships (target_id);
CREATE INDEX IF NOT EXISTS idx_rel_source_path ON relationships (source_path);

CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prov_dedup
    ON provenance (entity_id, source_path);

CREATE INDEX IF NOT EXISTS idx_prov_entity ON provenance (entity_id);
CREATE INDEX IF NOT EXISTS idx_prov_source ON provenance (source_path);

CREATE TABLE IF NOT EXISTS source_hashes (
    source_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _normalize(name: str) -> str:
    """Normalize an entity name for deduplication."""
    return name.lower().strip()


class GraphStore:
    """Async SQLite-backed graph storage.

    Stores entities and relationships as a derived index over the vault.
    Uses WAL mode for concurrent read access.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._rebuild_lock: asyncio.Lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open connection, enable WAL mode, and create tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        logger.info("graph_store_initialized", path=str(self._db_path))

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def commit(self) -> None:
        """Commit the current transaction."""
        async with self._write_lock:
            await self._conn.commit()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            msg = "GraphStore not initialized — call initialize() first"
            raise RuntimeError(msg)
        return self._db

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    async def upsert_entity(self, entity: GraphEntity) -> str:
        """Insert or update an entity, returning its (possibly existing) ID.

        Deduplicates on ``(name_normalized, entity_type)``.  When a duplicate
        is found the existing row is updated.  A provenance record is always
        added so that ``delete_by_source`` can correctly determine whether
        the entity should be removed when one of its sources is deleted.
        """
        async with self._write_lock:
            return await self._upsert_entity_locked(entity)

    async def _upsert_entity_locked(self, entity: GraphEntity) -> str:
        norm = _normalize(entity.name)
        row = await self._fetchone(
            "SELECT id FROM entities WHERE name_normalized = ? AND entity_type = ?",
            (norm, entity.entity_type),
        )
        if row:
            existing_id = row[0]
            await self._conn.execute(
                """UPDATE entities
                   SET source_path = ?, properties = ?, confidence = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    entity.source_path,
                    json.dumps(entity.properties),
                    entity.confidence,
                    existing_id,
                ),
            )
            # Record provenance for this source
            await self._conn.execute(
                """INSERT OR IGNORE INTO provenance
                   (entity_id, source_path, extraction_method, confidence, extracted_at)
                   VALUES (?, ?, 'rule', ?, datetime('now'))""",
                (existing_id, entity.source_path, entity.confidence),
            )
            return existing_id

        await self._conn.execute(
            """INSERT INTO entities (id, name, name_normalized, entity_type,
                                    source_path, properties, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entity.id,
                entity.name,
                norm,
                entity.entity_type,
                entity.source_path,
                json.dumps(entity.properties),
                entity.confidence,
            ),
        )
        # Record provenance for this source
        await self._conn.execute(
            """INSERT OR IGNORE INTO provenance
               (entity_id, source_path, extraction_method, confidence, extracted_at)
               VALUES (?, ?, 'rule', ?, datetime('now'))""",
            (entity.id, entity.source_path, entity.confidence),
        )
        return entity.id

    async def upsert_relationship(self, rel: GraphRelationship) -> str:
        """Insert a relationship, skipping duplicates on (source_id, target_id, rel_type)."""
        async with self._write_lock:
            return await self._upsert_relationship_locked(rel)

    async def _upsert_relationship_locked(self, rel: GraphRelationship) -> str:
        row = await self._fetchone(
            """SELECT id FROM relationships
               WHERE source_id = ? AND target_id = ? AND rel_type = ?""",
            (rel.source_id, rel.target_id, rel.rel_type),
        )
        if row:
            return row[0]

        await self._conn.execute(
            """INSERT INTO relationships
               (id, source_id, target_id, rel_type, source_path, properties, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                rel.id,
                rel.source_id,
                rel.target_id,
                rel.rel_type,
                rel.source_path,
                json.dumps(rel.properties),
                rel.confidence,
            ),
        )
        return rel.id

    async def delete_by_source(self, source_path: str) -> int:
        """Remove entities and relationships originating from a source path.

        Uses provenance to determine which entities to delete:
        - Removes provenance records for this source_path.
        - Deletes entities that have no remaining provenance records
          (i.e., not referenced by any other source).
        - Relationships with source_path matching are always deleted.
        - FK cascade handles relationships referencing deleted entities.

        Returns the number of deleted entities.
        """
        async with self._write_lock:
            return await self._delete_by_source_locked(source_path)

    async def _delete_by_source_locked(self, source_path: str) -> int:
        # 1. Delete relationships from this source
        await self._conn.execute("DELETE FROM relationships WHERE source_path = ?", (source_path,))

        # 2. Remove provenance records for this source
        await self._conn.execute("DELETE FROM provenance WHERE source_path = ?", (source_path,))

        # 3. Delete entities that have no remaining provenance AND
        #    whose current source_path matches (entities with other
        #    provenance records are kept).
        cursor = await self._conn.execute(
            """DELETE FROM entities
               WHERE source_path = ?
                 AND id NOT IN (SELECT entity_id FROM provenance)""",
            (source_path,),
        )

        # 4. Clean up source hash
        await self._conn.execute("DELETE FROM source_hashes WHERE source_path = ?", (source_path,))

        await self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    async def add_provenance(self, record: ProvenanceRecord) -> None:
        """Record extraction provenance for an entity.

        Skips duplicate (entity_id, source_path) combinations.
        """
        await self._conn.execute(
            """INSERT OR IGNORE INTO provenance (entity_id, source_path, extraction_method,
                                                confidence, extracted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                record.entity_id,
                record.source_path,
                record.extraction_method,
                record.confidence,
                record.extracted_at,
            ),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_entity_by_name(
        self, name: str, entity_type: str | None = None
    ) -> GraphEntity | None:
        """Look up an entity by (normalized) name and optional type."""
        norm = _normalize(name)
        if entity_type:
            row = await self._fetchone(
                "SELECT * FROM entities WHERE name_normalized = ? AND entity_type = ?",
                (norm, entity_type),
            )
        else:
            row = await self._fetchone("SELECT * FROM entities WHERE name_normalized = ?", (norm,))
        return self._row_to_entity(row) if row else None

    async def search_entities(self, query: str, *, limit: int = 20) -> list[GraphEntity]:
        """Search entities by name substring (case-insensitive)."""
        norm = _normalize(query)
        rows = await self._fetchall(
            """SELECT * FROM entities
               WHERE name_normalized LIKE '%' || ? || '%'
               ORDER BY name_normalized
               LIMIT ?""",
            (norm, limit),
        )
        return [self._row_to_entity(r) for r in rows]

    async def query_neighbors(
        self, entity_id: str, *, rel_type: str | None = None
    ) -> list[tuple[GraphRelationship, GraphEntity]]:
        """Find direct neighbors of an entity.

        Returns (relationship, neighbor_entity) pairs for both outgoing
        and incoming edges.
        """
        type_filter = "AND r.rel_type = ?" if rel_type else ""
        params: list[Any] = [entity_id]
        if rel_type:
            params.append(rel_type)
        params.append(entity_id)
        if rel_type:
            params.append(rel_type)

        sql = f"""
            SELECT r.id, r.source_id, r.target_id, r.rel_type,
                   r.source_path, r.properties, r.confidence,
                   e.id, e.name, e.name_normalized, e.entity_type,
                   e.source_path, e.properties, e.confidence
            FROM relationships r
            JOIN entities e ON e.id = r.target_id
            WHERE r.source_id = ? {type_filter}
            UNION ALL
            SELECT r.id, r.source_id, r.target_id, r.rel_type,
                   r.source_path, r.properties, r.confidence,
                   e.id, e.name, e.name_normalized, e.entity_type,
                   e.source_path, e.properties, e.confidence
            FROM relationships r
            JOIN entities e ON e.id = r.source_id
            WHERE r.target_id = ? {type_filter}
        """
        rows = await self._fetchall(sql, tuple(params))
        results: list[tuple[GraphRelationship, GraphEntity]] = []
        for row in rows:
            rel = GraphRelationship(
                source_id=row[1],
                target_id=row[2],
                rel_type=row[3],
                source_path=row[4],
                id=row[0],
                properties=json.loads(row[5]),
                confidence=row[6],
            )
            ent = GraphEntity(
                name=row[8],
                entity_type=row[10],
                source_path=row[11],
                id=row[7],
                properties=json.loads(row[12]),
                confidence=row[13],
            )
            results.append((rel, ent))
        return results

    async def multi_hop_query(
        self, entity_id: str, *, max_hops: int = 2
    ) -> list[tuple[int, GraphEntity]]:
        """BFS traversal from a starting entity up to ``max_hops`` depth.

        Returns ``(depth, entity)`` pairs, excluding the starting entity.
        Visited entities are never re-visited (cycle-safe).
        """
        visited: set[str] = {entity_id}
        frontier: list[str] = [entity_id]
        results: list[tuple[int, GraphEntity]] = []

        for depth in range(1, max_hops + 1):
            next_frontier: list[str] = []
            for eid in frontier:
                neighbors = await self.query_neighbors(eid)
                for _rel, neighbor in neighbors:
                    if neighbor.id not in visited:
                        visited.add(neighbor.id)
                        next_frontier.append(neighbor.id)
                        results.append((depth, neighbor))
            frontier = next_frontier
            if not frontier:
                break

        return results

    async def count_entities(self) -> int:
        """Return the total number of entities."""
        row = await self._fetchone("SELECT COUNT(*) FROM entities")
        return row[0] if row else 0

    async def count_relationships(self) -> int:
        """Return the total number of relationships."""
        row = await self._fetchone("SELECT COUNT(*) FROM relationships")
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Source content hashing (incremental rebuild)
    # ------------------------------------------------------------------

    async def get_source_hash(self, source_path: str) -> str | None:
        """Return the stored content hash for a source, or None."""
        row = await self._fetchone(
            "SELECT content_hash FROM source_hashes WHERE source_path = ?",
            (source_path,),
        )
        return row[0] if row else None

    async def set_source_hash(self, source_path: str, content_hash: str) -> None:
        """Store or update the content hash for a source."""
        await self._conn.execute(
            """INSERT OR REPLACE INTO source_hashes (source_path, content_hash, updated_at)
               VALUES (?, ?, datetime('now'))""",
            (source_path, content_hash),
        )

    async def remove_source_hash(self, source_path: str) -> None:
        """Remove the stored content hash for a source."""
        await self._conn.execute("DELETE FROM source_hashes WHERE source_path = ?", (source_path,))

    # ------------------------------------------------------------------
    # Vault rebuild
    # ------------------------------------------------------------------

    async def rebuild_from_vault(self, vault: Vault, extractor: GraphExtractor) -> dict[str, int]:
        """Rebuild graph from vault notes, skipping unchanged content.

        Returns a dict with ``notes_updated``, ``notes_skipped``,
        ``entities``, and ``relationships`` counts.

        Uses ``_rebuild_lock`` to prevent concurrent rebuilds.
        """
        async with self._rebuild_lock:
            return await self._rebuild_from_vault_locked(vault, extractor)

    async def _rebuild_from_vault_locked(
        self, vault: Vault, extractor: GraphExtractor
    ) -> dict[str, int]:
        count = 0
        skipped = 0
        for subdir in ("seeds", "garden"):
            base = vault.resolve_path(subdir)

            def _collect_md(p: Path = base) -> list[Path]:
                if not p.is_dir():
                    return []
                return sorted(p.rglob("*.md"))

            md_files = await asyncio.to_thread(_collect_md)
            for md_file in md_files:
                rel_path = str(md_file.relative_to(vault.root))
                try:
                    content = await vault.read_note_content(md_file)
                    content_hash = hashlib.sha256(content.encode()).hexdigest()

                    stored_hash = await self.get_source_hash(rel_path)
                    if stored_hash == content_hash:
                        skipped += 1
                        continue

                    async with self._write_lock:
                        await self._delete_by_source_locked(rel_path)
                        entities, rels = extractor.extract_from_note(rel_path, content)
                        id_map: dict[str, str] = {}
                        for entity in entities:
                            resolved_id = await self._upsert_entity_locked(entity)
                            id_map[entity.id] = resolved_id
                        for rel in rels:
                            resolved = dataclasses.replace(
                                rel,
                                source_id=id_map.get(rel.source_id, rel.source_id),
                                target_id=id_map.get(rel.target_id, rel.target_id),
                            )
                            await self._upsert_relationship_locked(resolved)
                        await self.set_source_hash(rel_path, content_hash)
                        await self._conn.commit()
                    count += 1
                except (FileNotFoundError, OSError, UnicodeDecodeError):
                    logger.debug("graph_rebuild_note_failed", path=rel_path, exc_info=True)

        return {
            "notes_updated": count,
            "notes_skipped": skipped,
            "entities": await self.count_entities(),
            "relationships": await self.count_relationships(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetchone(self, sql: str, params: tuple = ()) -> tuple[Any, ...] | None:
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[tuple[Any, ...]]:
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    @staticmethod
    def _row_to_entity(row: Any) -> GraphEntity:
        """Convert a raw SQLite row to a GraphEntity."""
        return GraphEntity(
            name=row[1],
            entity_type=row[3],
            source_path=row[4],
            id=row[0],
            properties=json.loads(row[5]),
            confidence=row[6],
        )
