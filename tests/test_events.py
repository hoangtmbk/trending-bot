import pytest
from orchestrator.events import EventBus


def test_subscribe_and_emit():
    bus = EventBus()
    received = []
    bus.subscribe("items_updated", lambda data: received.append(data))
    bus.emit("items_updated", {"source": "github", "count": 10})
    assert len(received) == 1
    assert received[0] == {"source": "github", "count": 10}


def test_multiple_subscribers():
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("items_updated", lambda data: results_a.append(data))
    bus.subscribe("items_updated", lambda data: results_b.append(data))
    bus.emit("items_updated", {"count": 5})
    assert len(results_a) == 1
    assert len(results_b) == 1


def test_emit_unknown_event_is_noop():
    bus = EventBus()
    bus.emit("nonexistent", {})  # should not raise


def test_subscriber_error_does_not_break_others():
    bus = EventBus()
    received = []

    def bad_handler(data):
        raise ValueError("boom")

    bus.subscribe("test", bad_handler)
    bus.subscribe("test", lambda data: received.append(data))
    bus.emit("test", {"ok": True})
    assert len(received) == 1


def test_events_are_isolated():
    bus = EventBus()
    a_received = []
    b_received = []
    bus.subscribe("event_a", lambda data: a_received.append(data))
    bus.subscribe("event_b", lambda data: b_received.append(data))
    bus.emit("event_a", {"a": 1})
    assert len(a_received) == 1
    assert len(b_received) == 0


def test_unsubscribe():
    bus = EventBus()
    received = []
    handler = lambda data: received.append(data)
    bus.subscribe("test", handler)
    bus.unsubscribe("test", handler)
    bus.emit("test", {"x": 1})
    assert len(received) == 0
