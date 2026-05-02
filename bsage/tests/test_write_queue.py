"""Tests for the SQLite write queue (Sprint 3 / S3-4).

The queue serializes all writes through a single asyncio task, so
SQLite's global write lock can never be contended by concurrent
asyncio tasks. Reads bypass the queue entirely.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from bsage.garden.write_queue import (
    QueueClosedError,
    QueueFullError,
    SQLiteWriteQueue,
    WriteOpFailedError,
)


@pytest.fixture()
async def queue_db(tmp_path: Path):
    """An initialized SQLite write queue with a tiny test table."""
    db_path = tmp_path / "queue.db"
    conn = await aiosqlite.connect(str(db_path))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT NOT NULL)"
    )
    await conn.commit()

    queue = SQLiteWriteQueue(conn, name="test", maxsize=128)
    await queue.start()
    try:
        yield queue, conn
    finally:
        await queue.stop()
        await conn.close()


class TestBasicOperation:
    async def test_submit_returns_writer_result(self, queue_db) -> None:
        queue, conn = queue_db

        async def insert() -> int:
            cursor = await conn.execute("INSERT INTO items (val) VALUES (?)", ("a",))
            await conn.commit()
            return cursor.lastrowid

        rowid = await queue.submit(insert)

        assert rowid is not None
        assert rowid > 0

    async def test_submit_propagates_writer_exception(self, queue_db) -> None:
        queue, _conn = queue_db

        async def boom() -> None:
            raise ValueError("boom")

        with pytest.raises(WriteOpFailedError) as info:
            await queue.submit(boom)
        assert isinstance(info.value.__cause__, ValueError)

    async def test_writer_continues_after_exception(self, queue_db) -> None:
        """A single failing op must not break the writer task."""
        queue, conn = queue_db

        async def boom() -> None:
            raise ValueError("boom")

        async def insert() -> int:
            cursor = await conn.execute("INSERT INTO items (val) VALUES (?)", ("ok",))
            await conn.commit()
            return cursor.lastrowid

        with pytest.raises(WriteOpFailedError):
            await queue.submit(boom)

        # Writer is still healthy and serves the next op.
        rowid = await queue.submit(insert)
        assert rowid > 0


class TestSerializationAndOrdering:
    async def test_concurrent_writes_all_succeed_no_lock_errors(self, queue_db) -> None:
        """100 concurrent submits → all succeed + lock errors == 0."""
        queue, conn = queue_db
        n = 100

        async def make_op(i: int):
            async def op() -> int:
                cursor = await conn.execute("INSERT INTO items (val) VALUES (?)", (f"v{i}",))
                await conn.commit()
                return cursor.lastrowid

            return op

        # Fire all 100 concurrently — *no* manual lock anywhere.
        ops = [await make_op(i) for i in range(n)]
        results = await asyncio.gather(
            *(queue.submit(op) for op in ops),
            return_exceptions=True,
        )

        # Every single one returned a rowid; nothing raised.
        assert all(isinstance(r, int) for r in results), [
            r for r in results if not isinstance(r, int)
        ]
        # And no SQLite OperationalError ('database is locked') leaked through.
        cursor = await conn.execute("SELECT COUNT(*) FROM items")
        row = await cursor.fetchone()
        assert row[0] == n

    async def test_writes_preserve_submit_order(self, queue_db) -> None:
        """Items inserted via the queue must keep submit-order in the DB."""
        queue, conn = queue_db
        n = 50

        async def make_op(i: int):
            async def op() -> None:
                await conn.execute("INSERT INTO items (val) VALUES (?)", (f"v{i:03d}",))
                await conn.commit()

            return op

        # NOTE: order = enqueue order. Concurrent submits would be racy
        # for ordering by definition, so we test the contract that *given
        # serial enqueue, the queue preserves that order at the DB layer*.
        for i in range(n):
            op = await make_op(i)
            await queue.submit(op)

        cursor = await conn.execute("SELECT val FROM items ORDER BY id")
        rows = [r[0] for r in await cursor.fetchall()]
        assert rows == [f"v{i:03d}" for i in range(n)]

    async def test_only_one_op_runs_at_a_time(self, queue_db) -> None:
        """While writer is running op A, op B must not have started yet."""
        queue, _conn = queue_db
        in_flight = 0
        max_in_flight = 0
        gate = asyncio.Event()

        async def slow_op(i: int) -> int:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                if i == 0:
                    # First op holds until released — without serialization
                    # subsequent ops would also bump in_flight before this
                    # returns.
                    await gate.wait()
                else:
                    await asyncio.sleep(0)
                return i
            finally:
                in_flight -= 1

        # Schedule op 0 first; it will block on `gate`. Then schedule
        # 9 more — they should all queue up behind it.
        first = asyncio.create_task(queue.submit(lambda: slow_op(0)))
        await asyncio.sleep(0.05)  # give writer time to pick up op 0
        rest = [asyncio.create_task(queue.submit(lambda i=i: slow_op(i))) for i in range(1, 10)]
        await asyncio.sleep(0.05)
        # Op 0 still in flight, others queued.
        assert in_flight == 1
        gate.set()
        await asyncio.gather(first, *rest)
        assert max_in_flight == 1


class TestBackpressure:
    async def test_submit_blocks_when_full_then_drains(self, tmp_path: Path) -> None:
        """When the queue is full, `submit` awaits until space frees."""
        db_path = tmp_path / "bp.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        # maxsize=2 forces backpressure quickly.
        queue = SQLiteWriteQueue(conn, name="bp", maxsize=2)
        await queue.start()
        try:
            gate = asyncio.Event()

            async def hold() -> None:
                await gate.wait()

            async def quick() -> None:
                pass

            # Block the writer with one op.
            holder = asyncio.create_task(queue.submit(hold))
            await asyncio.sleep(0.01)

            # Fill the queue to capacity.
            t1 = asyncio.create_task(queue.submit(quick))
            t2 = asyncio.create_task(queue.submit(quick))
            await asyncio.sleep(0.01)

            # Next submit must NOT complete immediately — queue is full.
            t3 = asyncio.create_task(queue.submit(quick))
            await asyncio.sleep(0.05)
            assert not t3.done()

            # Releasing the holder drains the queue.
            gate.set()
            await asyncio.gather(holder, t1, t2, t3)
        finally:
            await queue.stop()
            await conn.close()

    async def test_try_submit_rejects_when_full(self, tmp_path: Path) -> None:
        """`try_submit` is non-blocking and raises when full."""
        db_path = tmp_path / "try.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="try", maxsize=1)
        await queue.start()
        try:
            gate = asyncio.Event()

            async def hold() -> None:
                await gate.wait()

            holder = asyncio.create_task(queue.submit(hold))
            await asyncio.sleep(0.01)

            async def quick() -> None:
                pass

            # Fills the slot.
            await queue.try_submit(quick)
            # Now full.
            with pytest.raises(QueueFullError):
                await queue.try_submit(quick)

            gate.set()
            await holder
        finally:
            await queue.stop()
            await conn.close()


class TestShutdown:
    async def test_stop_drains_pending_ops(self, tmp_path: Path) -> None:
        """`stop()` must wait for queued ops to finish, not drop them."""
        db_path = tmp_path / "drain.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="drain", maxsize=128)
        await queue.start()

        async def insert(i: int):
            async def op() -> None:
                await conn.execute("INSERT INTO t (val) VALUES (?)", (f"v{i}",))
                await conn.commit()

            return op

        # Enqueue 20 ops.
        ops = [await insert(i) for i in range(20)]
        tasks = [asyncio.create_task(queue.submit(op)) for op in ops]
        await asyncio.sleep(0)  # let the writer pick them up

        # Stop — must drain all in-flight + queued ops.
        await queue.stop()
        await asyncio.gather(*tasks, return_exceptions=True)

        cursor = await conn.execute("SELECT COUNT(*) FROM t")
        row = await cursor.fetchone()
        assert row[0] == 20
        await conn.close()

    async def test_submit_after_stop_raises(self, tmp_path: Path) -> None:
        """Submits after `stop()` must fail fast, not hang."""
        db_path = tmp_path / "closed.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="closed", maxsize=4)
        await queue.start()
        await queue.stop()

        async def op() -> None:
            pass

        with pytest.raises(QueueClosedError):
            await queue.submit(op)
        await conn.close()


class TestSupervisor:
    async def test_writer_task_restarts_on_unexpected_crash(self, tmp_path: Path) -> None:
        """If the writer task itself crashes, the supervisor restarts it.

        We can't actually kill the asyncio task externally, so we
        simulate it by directly cancelling the writer — the
        ``add_done_callback`` supervisor MUST detect that and
        restart it for legitimate ops.
        """
        db_path = tmp_path / "crash.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="crash", maxsize=4)
        await queue.start()
        try:
            # Force the writer task to die by directly cancelling it.
            assert queue._writer_task is not None
            queue._writer_task.cancel()
            # Give supervisor time to notice + restart.
            await asyncio.sleep(0.05)

            # Service should be back online.
            async def insert() -> None:
                await conn.execute("INSERT INTO t (val) VALUES (?)", ("after-restart",))
                await conn.commit()

            await queue.submit(insert)
            cursor = await conn.execute("SELECT COUNT(*) FROM t")
            row = await cursor.fetchone()
            assert row[0] == 1
        finally:
            await queue.stop()
            await conn.close()

    async def test_pending_ops_failed_when_writer_crashes(self, tmp_path: Path) -> None:
        """Ops queued behind a crashed writer must surface ``WriteOpFailedError``.

        Otherwise callers wait forever on never-resolved futures.
        """
        db_path = tmp_path / "fail.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await conn.commit()

        queue = SQLiteWriteQueue(conn, name="fail", maxsize=8)
        await queue.start()
        try:
            gate = asyncio.Event()

            async def hold() -> None:
                await gate.wait()

            async def quick() -> None:
                pass

            holder = asyncio.create_task(queue.submit(hold))
            await asyncio.sleep(0.01)

            # These two are queued behind the holder.
            queued1 = asyncio.create_task(queue.submit(quick))
            queued2 = asyncio.create_task(queue.submit(quick))
            await asyncio.sleep(0.01)

            # Crash the writer mid-flight.
            assert queue._writer_task is not None
            queue._writer_task.cancel()
            await asyncio.sleep(0.05)

            # Pending ops behind the crash must have surfaced an error.
            for fut in (queued1, queued2):
                with pytest.raises(WriteOpFailedError):
                    await fut

            # The in-flight holder's future is also failed (writer
            # cancelled mid-flight) so the caller does not hang.
            with pytest.raises(WriteOpFailedError):
                await holder

            # Release the (no-longer-listening) gate so any orphan
            # waiter wakes up cleanly.
            gate.set()
        finally:
            await queue.stop()
            await conn.close()


class TestLifecycleEdgeCases:
    async def test_start_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "idem.db"
        conn = await aiosqlite.connect(str(db_path))
        queue = SQLiteWriteQueue(conn, name="idem", maxsize=4)
        await queue.start()
        first_task = queue._writer_task
        await queue.start()
        assert queue._writer_task is first_task  # not respawned
        await queue.stop()
        await conn.close()

    async def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "stop.db"
        conn = await aiosqlite.connect(str(db_path))
        queue = SQLiteWriteQueue(conn, name="stop", maxsize=4)
        await queue.start()
        await queue.stop()
        # Second stop must not raise.
        await queue.stop()
        await conn.close()

    async def test_try_submit_returns_future(self, tmp_path: Path) -> None:
        """`try_submit` returns the future so callers can `await` it."""
        db_path = tmp_path / "ts.db"
        conn = await aiosqlite.connect(str(db_path))
        queue = SQLiteWriteQueue(conn, name="ts", maxsize=4)
        await queue.start()
        try:

            async def quick() -> int:
                return 42

            fut = await queue.try_submit(quick)
            result = await fut
            assert result == 42
        finally:
            await queue.stop()
            await conn.close()

    async def test_try_submit_after_stop_raises(self, tmp_path: Path) -> None:
        db_path = tmp_path / "tsclose.db"
        conn = await aiosqlite.connect(str(db_path))
        queue = SQLiteWriteQueue(conn, name="tsclose", maxsize=4)
        await queue.start()
        await queue.stop()

        async def op() -> None:
            pass

        with pytest.raises(QueueClosedError):
            await queue.try_submit(op)
        await conn.close()
