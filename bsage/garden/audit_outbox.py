"""Phase Audit Batch 2 — raw aiosqlite audit outbox for BSage.

BSage stores its operational state in raw aiosqlite (graph.db, vectors.db)
rather than SQLAlchemy. The shared :mod:`bsvibe_audit` package ships a
SQLAlchemy outbox + relay (``register_audit_outbox_with`` / ``OutboxRelay``)
that assumes a declarative ``Base.metadata`` and ``AsyncSession``. We
deliberately do **not** adopt SQLAlchemy here (Phase A Batch 5 confirmed
BSage stays raw aiosqlite); instead this module reuses every other piece
of the bsvibe-audit contract:

* the typed Pydantic events (``KnowledgeEntryCreated`` etc.)
* the wire JSON shape produced by ``event.model_dump(mode="json")``
* :class:`bsvibe_audit.AuditClient` for transport and retry-class semantics

… and re-implements only the storage/relay glue against aiosqlite. The
table layout mirrors :class:`bsvibe_audit.AuditOutboxRecord` so an
operator switching products only sees one outbox vocabulary.

The outbox lives in its own SQLite database (``{vault_path}/.bsage/
audit_outbox.db``) so audit emit cannot stall the knowledge-graph writer
queue and vice versa. Each emit acquires a short asyncio lock — outbox
writes are tiny and mostly tail the WAL — and the relay polls in a
background task started from the gateway lifespan.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog
from bsvibe_audit import AuditClient, AuditDeliveryError, AuditSettings
from bsvibe_audit.events import AuditEventBase

logger = structlog.get_logger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    delivered_at TEXT DEFAULT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT DEFAULT NULL,
    next_attempt_at TEXT DEFAULT NULL,
    dead_letter INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_audit_outbox_undelivered
    ON audit_outbox (delivered_at, next_attempt_at);
"""


def _isoformat(dt: datetime) -> str:
    """Serialise tz-aware datetimes to ISO-8601 with explicit UTC suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Python's fromisoformat handles offsets in 3.11+.
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _backoff_seconds(retry_count: int) -> float:
    """Exponential backoff capped at one minute (matches bsvibe-audit §3.2)."""
    return min(60.0, 2.0 ** max(0, retry_count - 1))


class AiosqliteAuditOutbox:
    """Raw aiosqlite-backed audit outbox.

    Provides the minimal surface BSage needs: ``insert`` (called from
    request handlers + GardenWriter), ``select_undelivered`` /
    ``mark_delivered`` / ``record_failure`` (called by the relay), and
    a lifecycle pair (``initialize`` / ``close``).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._db is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        logger.info("audit_outbox_initialized", path=str(self._db_path))

    async def close(self) -> None:
        if self._db is None:
            return
        with suppress(Exception):
            await self._db.close()
        self._db = None

    @property
    def is_open(self) -> bool:
        return self._db is not None

    async def insert_event(self, event: AuditEventBase) -> int:
        """Serialise ``event`` and append it to the outbox.

        Returns the row id. Raises :class:`RuntimeError` if the outbox
        was never initialised — callers must check :attr:`is_open` (or
        use the higher-level emit helper which short-circuits silently).
        """
        if self._db is None:
            raise RuntimeError("AiosqliteAuditOutbox not initialised")
        payload: dict[str, Any] = event.model_dump(mode="json")
        async with self._lock:
            cursor = await self._db.execute(
                """
                INSERT INTO audit_outbox
                    (event_id, event_type, occurred_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(event.event_id),
                    event.event_type,
                    _isoformat(event.occurred_at),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            await self._db.commit()
            row_id = cursor.lastrowid or 0
        return int(row_id)

    async def select_undelivered(self, *, batch_size: int) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        now_iso = _isoformat(datetime.now(tz=UTC))
        async with self._lock:
            cursor = await self._db.execute(
                """
                SELECT id, event_id, event_type, occurred_at, payload,
                       retry_count, next_attempt_at
                FROM audit_outbox
                WHERE delivered_at IS NULL
                  AND dead_letter = 0
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY id ASC
                LIMIT ?
                """,
                (now_iso, batch_size),
            )
            rows = await cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row[4])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            out.append(
                {
                    "id": int(row[0]),
                    "event_id": row[1],
                    "event_type": row[2],
                    "occurred_at": row[3],
                    "payload": payload,
                    "retry_count": int(row[5] or 0),
                    "next_attempt_at": row[6],
                }
            )
        return out

    async def mark_delivered(self, ids: Iterable[int]) -> None:
        ids_list = [int(i) for i in ids]
        if not ids_list or self._db is None:
            return
        placeholders = ",".join("?" for _ in ids_list)
        now_iso = _isoformat(datetime.now(tz=UTC))
        async with self._lock:
            await self._db.execute(
                f"""
                UPDATE audit_outbox
                   SET delivered_at = ?, last_error = NULL
                 WHERE id IN ({placeholders})
                """,
                [now_iso, *ids_list],
            )
            await self._db.commit()

    async def record_failure(
        self,
        row_id: int,
        *,
        error: str,
        max_retries: int,
        retryable: bool,
    ) -> None:
        if self._db is None:
            return
        async with self._lock:
            cursor = await self._db.execute(
                "SELECT retry_count FROM audit_outbox WHERE id = ?",
                (row_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return
            new_count = int(row[0] or 0) + 1
            dead = (not retryable) or new_count >= max_retries
            next_at_iso: str | None
            if not retryable:
                next_at_iso = None
            else:
                next_at = datetime.now(tz=UTC).timestamp() + _backoff_seconds(new_count)
                next_at_iso = _isoformat(datetime.fromtimestamp(next_at, tz=UTC))
            await self._db.execute(
                """
                UPDATE audit_outbox
                   SET retry_count = ?, last_error = ?,
                       next_attempt_at = ?, dead_letter = ?
                 WHERE id = ?
                """,
                (new_count, error[:500], next_at_iso, 1 if dead else 0, row_id),
            )
            await self._db.commit()

    # -- introspection helpers (used by tests + future audit-cli) --------

    async def count_pending(self) -> int:
        if self._db is None:
            return 0
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM audit_outbox WHERE delivered_at IS NULL AND dead_letter = 0"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


class AiosqliteOutboxRelay:
    """Background relay for :class:`AiosqliteAuditOutbox`.

    Mirrors the lifecycle of :class:`bsvibe_audit.OutboxRelay` (start /
    stop / run_once) but reads from raw aiosqlite. The transport is the
    shared :class:`bsvibe_audit.AuditClient` so wire format and retry
    classification stay identical to the SQLAlchemy variant used by
    BSupervisor / BSGateway / BSNexus.
    """

    def __init__(
        self,
        *,
        outbox: AiosqliteAuditOutbox,
        client: AuditClient | None,
        batch_size: int = 50,
        interval_s: float = 5.0,
        max_retries: int = 5,
        enabled: bool = True,
    ) -> None:
        self._outbox = outbox
        self._client = client
        self._batch_size = batch_size
        self._interval_s = interval_s
        self._max_retries = max_retries
        self._enabled = enabled and client is not None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._logger = structlog.get_logger("bsage.audit_outbox.relay")

    @classmethod
    def from_settings(
        cls,
        settings: AuditSettings,
        *,
        outbox: AiosqliteAuditOutbox,
        client: AuditClient | None = None,
    ) -> AiosqliteOutboxRelay:
        if not settings.relay_enabled:
            return cls(outbox=outbox, client=None, enabled=False)
        if client is None:
            client = AuditClient.from_settings(
                audit_url=settings.auth_audit_url,
                service_token=settings.auth_service_token,
            )
        return cls(
            outbox=outbox,
            client=client,
            batch_size=settings.batch_size,
            interval_s=settings.relay_interval_s,
            max_retries=settings.max_retries,
            enabled=True,
        )

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self._enabled:
            self._logger.info("audit_relay_disabled")
            return
        if self.is_running():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="bsage-audit-relay")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            self._task = None
        if self._client is not None:
            with suppress(Exception):
                await self._client.aclose()

    async def run_once(self) -> int:
        if not self._enabled or self._client is None:
            return 0
        rows = await self._outbox.select_undelivered(batch_size=self._batch_size)
        if not rows:
            return 0
        payloads = [row["payload"] for row in rows]
        ids = [row["id"] for row in rows]
        try:
            await self._client.send(payloads)
        except AuditDeliveryError as exc:
            for row_id in ids:
                await self._outbox.record_failure(
                    row_id,
                    error=str(exc),
                    max_retries=self._max_retries,
                    retryable=exc.retryable,
                )
            self._logger.warning(
                "audit_batch_failed",
                rows=len(rows),
                retryable=exc.retryable,
                error=str(exc),
            )
            return 0
        await self._outbox.mark_delivered(ids)
        self._logger.debug("audit_batch_delivered", rows=len(rows))
        return len(rows)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001 — relay must survive
                self._logger.error("audit_relay_iteration_failed", error=repr(exc))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)
            except TimeoutError:
                continue


async def safe_emit(
    outbox: AiosqliteAuditOutbox | None,
    event: AuditEventBase,
) -> None:
    """Emit an audit event without ever raising into the request handler.

    sync API regression guard: knowledge endpoints must keep their
    response contract even when audit infra hiccups. Failures are
    logged via structlog and swallowed so the route still returns 201.
    """
    if outbox is None or not outbox.is_open:
        return
    try:
        await outbox.insert_event(event)
    except Exception:  # noqa: BLE001 - audit must never break the domain write
        logger.warning("audit_emit_failed", event_type=event.event_type, exc_info=True)


def new_event_id() -> str:
    return str(uuid.uuid4())


__all__ = [
    "AiosqliteAuditOutbox",
    "AiosqliteOutboxRelay",
    "safe_emit",
    "new_event_id",
]
