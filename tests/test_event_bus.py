# ----------------------------------------------------------------------------------------------------
# test_event_bus.py
# ----------------------------------------------------------------------------------------------------

"""Tests for the EventBus pub/sub system."""

# ----------------------------------------------------------------------------------------------------
import threading
import time

from core.event_bus import EventBus


# ----------------------------------------------------------------------------------------------------
class TestEventBusBasic:
    """
    Basic subscribe/emit/unsubscribe behavior.
    """
# ----------------------------------------------------------------------------------------------------
    def test_subscribe_and_emit(self):
        bus = EventBus()
        results = []

        def handler(data):
            results.append(data)

        bus.subscribe("test_event", handler)
        bus.emit("test_event", {"key": "value"})

        time.sleep(0.1)  # Allow thread to execute
        assert results == [{"key": "value"}]

# ----------------------------------------------------------------------------------------------------
    def test_emit_without_data(self):
        bus = EventBus()
        called = []

        def handler():
            called.append(True)

        bus.subscribe("ping", handler)
        bus.emit("ping")

        time.sleep(0.1)
        assert called == [True]

# ----------------------------------------------------------------------------------------------------
    def test_multiple_subscribers(self):
        bus = EventBus()
        results_a = []
        results_b = []

        def handler_a(data):
            results_a.append(data)

        def handler_b(data):
            results_b.append(data)

        bus.subscribe("event", handler_a)
        bus.subscribe("event", handler_b)
        bus.emit("event", {"msg": "hello"})

        time.sleep(0.1)
        assert results_a == [{"msg": "hello"}]
        assert results_b == [{"msg": "hello"}]

# ----------------------------------------------------------------------------------------------------
    def test_emit_unknown_event_no_error(self):
        bus = EventBus()
        # Should not raise
        bus.emit("nonexistent_event", {"data": 1})
        bus.emit("another_missing")

# ----------------------------------------------------------------------------------------------------
    def test_unsubscribe(self):
        bus = EventBus()
        results = []

        def handler(data):
            results.append(data)

        bus.subscribe("event", handler)
        bus.emit("event", {"first": True})
        time.sleep(0.1)

        bus.unsubscribe("event", handler)
        bus.emit("event", {"second": True})
        time.sleep(0.1)

        assert results == [{"first": True}]

# ----------------------------------------------------------------------------------------------------
    def test_unsubscribe_nonexistent_callback(self):
        bus = EventBus()

        def handler():
            pass

        # Should not raise
        bus.unsubscribe("event", handler)

# ----------------------------------------------------------------------------------------------------
    def test_unsubscribe_nonexistent_event(self):
        bus = EventBus()

        def handler():
            pass

        # Should not raise
        bus.unsubscribe("never_registered", handler)

# ----------------------------------------------------------------------------------------------------
    def test_duplicate_subscribe_ignored(self):
        bus = EventBus()
        results = []

        def handler(data):
            results.append(data)

        bus.subscribe("event", handler)
        bus.subscribe("event", handler)  # Duplicate
        bus.emit("event", {"val": 1})

        time.sleep(0.1)
        assert results == [{"val": 1}]  # Called only once

# ----------------------------------------------------------------------------------------------------
class TestEventBusThreadSafety:
    """
    Verify thread-safe operation under concurrent access.
    """

# ----------------------------------------------------------------------------------------------------
    def test_concurrent_subscribe_emit(self):
        bus = EventBus()
        results = []
        lock = threading.Lock()

        def handler(data):
            with lock:
                results.append(data)

        def subscriber():
            for i in range(50):
                bus.subscribe(f"event_{i % 5}", handler)

        def emitter():
            for i in range(50):
                bus.emit(f"event_{i % 5}", {"i": i})

        threads = []
        for _ in range(4):
            threads.append(threading.Thread(target=subscriber))
            threads.append(threading.Thread(target=emitter))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        time.sleep(0.5)
        # No crashes or deadlocks — success is completing without error
        assert len(results) > 0

# ----------------------------------------------------------------------------------------------------
    def test_subscriber_exception_does_not_crash_bus(self):
        bus = EventBus()
        results = []

        def bad_handler(data):
            raise ValueError("I broke!")

        def good_handler(data):
            results.append(data)

        bus.subscribe("event", bad_handler)
        bus.subscribe("event", good_handler)
        bus.emit("event", {"test": True})

        time.sleep(0.1)
        # Good handler still called despite bad handler raising
        assert results == [{"test": True}]
