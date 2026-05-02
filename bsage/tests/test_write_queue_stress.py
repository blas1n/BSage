"""Sprint 4 — write queue stress + supervisor regression suite.

Sprint 3 introduced :class:`SQLiteWriteQueue` to serialize all SQLite
writes through a single asyncio task. The companion ``test_write_queue.py``
suite exercises correctness on small workloads (≤100 ops). This file
extends coverage to the cases the audit (§7.5 + Sprint 3 / S3-4)
specifically called out as risk:

* **Throughput**: 1000+ concurrent ``submit`` calls — every write
  must land, in order, with no ``database is locked`` errors.
* **Mixed pressure**: ``submit`` + ``try_submit`` interleaved against
  a saturated queue — fail-fast must reject cleanly without breaking
  the slower blocking submitters.
* **Supervisor recovery**: the writer task can crash for a number of
  reasons (event-loop shutdown signal, native cancel, runaway op).
  Across a *sequence* of crashes, the queue must continue to serve
  new submits — proving the supervisor is itself idempotent.

These tests are heavier than the others (~2-3s wall) but still
deterministic — they do not poll, sleep-loop, or rely on real time.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from bsage.garden.write_queue import (
    QueueFullError,
    SQLiteWriteQueue,
    WriteOpFailedError,
)

# ---------------------------------------------------------------------------
# Throughput: 1000+ concurrent submits
# ---------------------------------------------------------------------------


@pytest.fixture()
async def stress_queue(tmp_path: Path):
    """A queue + connection sized for stress workloads."""
    db_path = tmp_path / "stress.db"
    conn = await aiosqlite.connect(str(db_path))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute(
        "CREATE TABLE items (  id INTEGER PRIMARY KEY AUTOINCREMENT,  val TEXT NOT NULL)"
    )
    await conn.commit()

    # maxsize must be >= submit batch — backpressure is tested
    # separately. We are isolating throughput here.
    queue = SQLiteWriteQueue(conn, name="stress", maxsize=2048)
    await queue.start()
    try:
        yield queue, conn
    finally:
        await queue.stop()
        await conn.close()


class TestThroughputUnderConcurrency:
    """Audit §7.5: under 5+ plugins firing at once, the queue must
    serialize writes without losing any of them."""

    async def test_one_thousand_concurrent_submits_all_succeed(self, stress_queue) -> None:
        """1000 concurrent ``submit`` calls — every one must land,
        ordering preserved per submitter, zero lock errors."""
        queue, conn = stress_queue
        n = 1000

        async def make_op(i: int):
            async def op() -> int:
                cursor = await conn.execute("INSERT INTO items (val) VALUES (?)", (f"v{i:04d}",))
                await conn.commit()
                assert cursor.lastrowid is not None
                return cursor.lastrowid

            return op

        ops = [await make_op(i) for i in range(n)]
        results = await asyncio.gather(
            *(queue.submit(op) for op in ops),
            return_exceptions=True,
        )

        # Every single op resolved without exception.
        failures = [r for r in results if not isinstance(r, int)]
        assert not failures, f"{len(failures)} ops failed: {failures[:3]}"

        # Total row count matches exactly.
        cursor = await conn.execute("SELECT COUNT(*) FROM items")
        row = await cursor.fetchone()
        assert row[0] == n

        # No duplicate rowids — proves the writer task didn't run
        # ops in parallel (which would corrupt the autoincrement).
        cursor = await conn.execute("SELECT COUNT(DISTINCT id) FROM items")
        row = await cursor.fetchone()
        assert row[0] == n

    async def test_two_thousand_submits_against_small_queue_backpressures(
        self, tmp_path: Path
    ) -> None:
        """2000 submits against ``maxsize=64`` — the queue must apply
        backpressure (some submits await capacity) and still resolve
        every op. This is the realistic plugin-fanout scenario."""
        db_path = tmp_path / "bp_stress.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="bpstress", maxsize=64)
        await queue.start()
        try:

            async def insert():
                async def op() -> None:
                    await conn.execute("INSERT INTO t DEFAULT VALUES")
                    await conn.commit()

                return op

            n = 2000
            ops = [await insert() for _ in range(n)]
            results = await asyncio.gather(
                *(queue.submit(op) for op in ops),
                return_exceptions=True,
            )

            failures = [r for r in results if isinstance(r, BaseException)]
            assert not failures, f"{len(failures)} ops failed under backpressure"

            cursor = await conn.execute("SELECT COUNT(*) FROM t")
            row = await cursor.fetchone()
            assert row[0] == n
        finally:
            await queue.stop()
            await conn.close()


# ---------------------------------------------------------------------------
# Mixed submit + try_submit pressure
# ---------------------------------------------------------------------------


class TestMixedSubmitAndTrySubmit:
    """``submit`` (blocking) and ``try_submit`` (fail-fast) must coexist
    correctly when the queue is saturated. ``try_submit`` rejections
    must not corrupt the in-flight queue or abandon the blocked
    submitters."""

    async def test_try_submit_rejects_dont_block_submit_drain(self, tmp_path: Path) -> None:
        """A burst of ``try_submit`` calls hits a full queue. Half are
        rejected, half land. After the holder releases, the remaining
        ops drain cleanly — no deadlock, no orphan futures."""
        db_path = tmp_path / "mixed.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        # maxsize=4 → easy to saturate.
        queue = SQLiteWriteQueue(conn, name="mixed", maxsize=4)
        await queue.start()
        try:
            gate = asyncio.Event()

            async def hold() -> None:
                await gate.wait()

            async def quick() -> None:
                await conn.execute("INSERT INTO t DEFAULT VALUES")
                await conn.commit()

            # 1) Block the writer.
            holder = asyncio.create_task(queue.submit(hold))
            await asyncio.sleep(0.01)

            # 2) Fill the slot capacity to maxsize.
            futures: list[asyncio.Future] = []
            for _ in range(4):
                futures.append(await queue.try_submit(quick))

            # 3) Now everything else must fail-fast OR block.
            #    Mix the two: 6 try_submits (must raise) and 5 submits
            #    (must await capacity).
            rejected = 0
            for _ in range(6):
                with pytest.raises(QueueFullError):
                    await queue.try_submit(quick)
                rejected += 1
            assert rejected == 6

            blocking = [asyncio.create_task(queue.submit(quick)) for _ in range(5)]
            # None of those should be done yet — the holder is still active.
            await asyncio.sleep(0.05)
            assert not any(t.done() for t in blocking)

            # 4) Release the holder; writer drains everything.
            gate.set()
            await asyncio.gather(holder, *futures, *blocking)

            # All accepted ops landed: 4 try_submitted + 5 submitted = 9.
            cursor = await conn.execute("SELECT COUNT(*) FROM t")
            row = await cursor.fetchone()
            assert row[0] == 9
        finally:
            await queue.stop()
            await conn.close()


# ---------------------------------------------------------------------------
# Supervisor recovery from a sequence of crashes
# ---------------------------------------------------------------------------


class TestSupervisorRepeatedCrashRecovery:
    """The single-test ``TestSupervisor`` case in ``test_write_queue.py``
    proves a single restart works. This case proves the supervisor is
    *idempotent*: across N consecutive crashes the queue keeps serving."""

    async def test_repeated_writer_crash_then_continued_service(self, tmp_path: Path) -> None:
        """Crash → restart → write → crash → restart → write … N times.

        After every crash the supervisor must:
        - replace the writer task,
        - fail every queued op so callers don't hang,
        - accept new submits.
        """
        db_path = tmp_path / "repeat_crash.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="repeat", maxsize=8)
        await queue.start()
        try:
            successful_writes = 0
            for round_idx in range(5):
                # Crash the writer.
                assert queue._writer_task is not None
                queue._writer_task.cancel()
                await asyncio.sleep(0.05)

                # Service must be healthy again — perform a write.
                async def insert(idx: int = round_idx) -> None:
                    await conn.execute("INSERT INTO t (val) VALUES (?)", (f"round-{idx}",))
                    await conn.commit()

                await queue.submit(insert)
                successful_writes += 1

            cursor = await conn.execute("SELECT COUNT(*) FROM t")
            row = await cursor.fetchone()
            assert row[0] == successful_writes == 5

            # And the writer task is ALIVE — supervisor left a healthy task.
            assert queue._writer_task is not None
            assert not queue._writer_task.done()
        finally:
            await queue.stop()
            await conn.close()

    async def test_op_raising_unexpected_exception_does_not_kill_writer(
        self, tmp_path: Path
    ) -> None:
        """An op that raises a non-asyncio exception must surface as
        ``WriteOpFailedError`` — but the writer keeps draining the
        queue, no supervisor restart needed.

        This is distinct from ``test_writer_continues_after_exception``
        in the base suite: here we fire a *burst* of failures
        interleaved with successes, simulating a bad plugin spamming
        broken ops at a healthy queue."""
        db_path = tmp_path / "burst_fail.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="burst", maxsize=64)
        await queue.start()
        try:

            async def boom(i: int):
                async def op() -> None:
                    raise ValueError(f"boom-{i}")

                return op

            async def insert():
                async def op() -> None:
                    await conn.execute("INSERT INTO t DEFAULT VALUES")
                    await conn.commit()

                return op

            tasks: list[asyncio.Future] = []
            for i in range(20):
                # 1 success per 1 failure, alternating.
                tasks.append(asyncio.create_task(queue.submit(await boom(i))))
                tasks.append(asyncio.create_task(queue.submit(await insert())))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Half failed (WriteOpFailedError), half None / no exception.
            failures = [r for r in results if isinstance(r, WriteOpFailedError)]
            successes = [r for r in results if not isinstance(r, BaseException)]
            assert len(failures) == 20
            assert len(successes) == 20

            # The successful inserts all landed.
            cursor = await conn.execute("SELECT COUNT(*) FROM t")
            row = await cursor.fetchone()
            assert row[0] == 20

            # Writer is still healthy — no supervisor restart was needed.
            assert queue._writer_task is not None
            assert not queue._writer_task.done()
        finally:
            await queue.stop()
            await conn.close()
