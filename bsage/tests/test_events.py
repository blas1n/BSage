"""Tests for bsage.core.events — EventBus, Event, EventType."""

from unittest.mock import AsyncMock

import pytest

from bsage.core.events import Event, EventBus, EventSubscriber, EventType


class TestEventType:
    """Test EventType enum."""

    def test_all_values_are_unique(self) -> None:
        values = [e.value for e in EventType]
        assert len(values) == len(set(values))

    def test_expected_types_exist(self) -> None:
        assert EventType.PLUGIN_RUN_START.value == "plugin_run_start"
        assert EventType.SKILL_GATHER_COMPLETE.value == "skill_gather_complete"
        assert EventType.SEED_WRITTEN.value == "seed_written"
        assert EventType.TRIGGER_FIRED.value == "trigger_fired"
        assert EventType.TOOL_CALL_START.value == "tool_call_start"
        assert EventType.INPUT_RECEIVED.value == "input_received"


class TestEvent:
    """Test Event dataclass."""

    def test_fields_populated(self) -> None:
        event = Event(event_type=EventType.PLUGIN_RUN_START, payload={"name": "test"})
        assert event.event_type == EventType.PLUGIN_RUN_START
        assert event.payload == {"name": "test"}
        assert event.correlation_id  # auto-generated UUID
        assert event.timestamp  # auto-generated ISO timestamp

    def test_to_dict_format(self) -> None:
        event = Event(
            event_type=EventType.SEED_WRITTEN,
            payload={"path": "/vault/seeds/test.md"},
            correlation_id="abc-123",
        )
        d = event.to_dict()
        assert d["type"] == "event"
        assert d["event_type"] == "seed_written"
        assert d["correlation_id"] == "abc-123"
        assert d["payload"]["path"] == "/vault/seeds/test.md"
        assert "timestamp" in d

    def test_auto_generated_correlation_id(self) -> None:
        e1 = Event(event_type=EventType.PLUGIN_RUN_START)
        e2 = Event(event_type=EventType.PLUGIN_RUN_START)
        assert e1.correlation_id != e2.correlation_id

    def test_custom_correlation_id(self) -> None:
        event = Event(event_type=EventType.PLUGIN_RUN_START, correlation_id="custom-id")
        assert event.correlation_id == "custom-id"

    def test_default_empty_payload(self) -> None:
        event = Event(event_type=EventType.TRIGGER_FIRED)
        assert event.payload == {}


class TestEventBus:
    """Test EventBus pub/sub."""

    async def test_emit_calls_subscriber(self) -> None:
        bus = EventBus()
        sub = AsyncMock(spec=EventSubscriber)
        bus.subscribe(sub)

        event = Event(event_type=EventType.PLUGIN_RUN_START)
        await bus.emit(event)

        sub.on_event.assert_awaited_once_with(event)

    async def test_emit_calls_all_subscribers(self) -> None:
        bus = EventBus()
        sub1 = AsyncMock(spec=EventSubscriber)
        sub2 = AsyncMock(spec=EventSubscriber)
        bus.subscribe(sub1)
        bus.subscribe(sub2)

        event = Event(event_type=EventType.SEED_WRITTEN)
        await bus.emit(event)

        sub1.on_event.assert_awaited_once_with(event)
        sub2.on_event.assert_awaited_once_with(event)

    async def test_subscriber_failure_does_not_propagate(self) -> None:
        bus = EventBus()
        sub = AsyncMock(spec=EventSubscriber)
        sub.on_event.side_effect = RuntimeError("boom")
        bus.subscribe(sub)

        event = Event(event_type=EventType.PLUGIN_RUN_ERROR)
        # Should not raise
        await bus.emit(event)

    async def test_subscriber_failure_does_not_block_others(self) -> None:
        bus = EventBus()
        bad_sub = AsyncMock(spec=EventSubscriber)
        bad_sub.on_event.side_effect = RuntimeError("fail")
        good_sub = AsyncMock(spec=EventSubscriber)

        bus.subscribe(bad_sub)
        bus.subscribe(good_sub)

        event = Event(event_type=EventType.PLUGIN_RUN_START)
        await bus.emit(event)

        good_sub.on_event.assert_awaited_once_with(event)

    async def test_emit_no_subscribers(self) -> None:
        bus = EventBus()
        event = Event(event_type=EventType.TRIGGER_FIRED)
        # Should not raise
        await bus.emit(event)

    def test_subscribe_adds_subscriber(self) -> None:
        bus = EventBus()
        sub = AsyncMock(spec=EventSubscriber)
        bus.subscribe(sub)
        assert sub in bus._subscribers

    def test_unsubscribe_removes_subscriber(self) -> None:
        bus = EventBus()
        sub = AsyncMock(spec=EventSubscriber)
        bus.subscribe(sub)
        bus.unsubscribe(sub)
        assert sub not in bus._subscribers

    def test_unsubscribe_nonexistent_raises(self) -> None:
        bus = EventBus()
        sub = AsyncMock(spec=EventSubscriber)
        with pytest.raises(ValueError):
            bus.unsubscribe(sub)
