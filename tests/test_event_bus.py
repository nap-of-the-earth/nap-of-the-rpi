# ----------------------------------------------------------------------------------------------------
# test_event_bus.py
# ----------------------------------------------------------------------------------------------------

"""
Tests for the EventBus pub/sub system.

These tests verify that the EventBus correctly handles:
- Basic subscribe → emit → callback flow
- Multiple subscribers on the same event
- Unsubscribing (stop receiving events)
- Edge cases (unknown events, duplicate subscriptions)
- Thread safety (many threads using the bus simultaneously)
- Error isolation (one bad callback doesn't break others)

HOW PYTHON TESTING WORKS:
- We use pytest (a testing framework). It automatically discovers functions starting with "test_"
- Each test function creates a fresh EventBus, does something, and checks the result with "assert"
- "assert X == Y" means "crash the test if X doesn't equal Y"
- time.sleep(0.1) gives background threads time to run before we check results
  (because emit() is non-blocking — it returns immediately while callbacks run in threads)

RUN TESTS WITH:
    uv run pytest tests/test_event_bus.py -v
"""

# ----------------------------------------------------------------------------------------------------
import threading
import time

# Import the class we're testing
from core.event_bus import EventBus


# ----------------------------------------------------------------------------------------------------
class TestEventBusBasic:
    """
    Basic subscribe/emit/unsubscribe behavior.

    Each test method is independent — pytest runs them in any order.
    The class is just for grouping related tests together.
    """

# ----------------------------------------------------------------------------------------------------
    def test_subscribe_and_emit(self):
        """Verify that a subscribed callback receives emitted data."""
        bus = EventBus()
        results = []  # We'll collect results here to verify later

        # Define a callback function — this is what gets called when the event fires
        def handler(data):
            results.append(data)

        # Subscribe: "when 'test_event' fires, call handler"
        bus.subscribe("test_event", handler)

        # Emit: "hey everyone, 'test_event' just happened, here's the data"
        bus.emit("test_event", {"key": "value"})

        # Wait a bit — emit() runs callbacks in background threads,
        # so we need to give them time to execute before checking
        time.sleep(0.1)

        # Verify the handler was called with the correct data
        assert results == [{"key": "value"}]

# ----------------------------------------------------------------------------------------------------
    def test_emit_without_data(self):
        """Verify that emit works when no data dict is provided."""
        bus = EventBus()
        called = []

        # This handler takes no arguments — useful for simple notifications
        # like "ping" or "shutdown" where no extra info is needed
        def handler():
            called.append(True)

        bus.subscribe("ping", handler)
        bus.emit("ping")  # No data argument

        time.sleep(0.1)
        assert called == [True]

# ----------------------------------------------------------------------------------------------------
    def test_multiple_subscribers(self):
        """Verify that ALL subscribers receive the event, not just the first one."""
        bus = EventBus()
        results_a = []
        results_b = []

        def handler_a(data):
            results_a.append(data)

        def handler_b(data):
            results_b.append(data)

        # Both handlers subscribe to the same event
        bus.subscribe("event", handler_a)
        bus.subscribe("event", handler_b)
        bus.emit("event", {"msg": "hello"})

        time.sleep(0.1)
        # Both should have received the data
        assert results_a == [{"msg": "hello"}]
        assert results_b == [{"msg": "hello"}]

# ----------------------------------------------------------------------------------------------------
    def test_emit_unknown_event_no_error(self):
        """Emitting an event with no subscribers should silently do nothing (not crash)."""
        bus = EventBus()
        # These should NOT raise any exception — they just have no effect
        bus.emit("nonexistent_event", {"data": 1})
        bus.emit("another_missing")
        # If we reach here without crashing, the test passes

# ----------------------------------------------------------------------------------------------------
    def test_unsubscribe(self):
        """After unsubscribing, the callback should no longer be called."""
        bus = EventBus()
        results = []

        def handler(data):
            results.append(data)

        bus.subscribe("event", handler)
        bus.emit("event", {"first": True})
        time.sleep(0.1)
        # handler was called for the first emit

        # Now unsubscribe — handler should no longer be called
        bus.unsubscribe("event", handler)
        bus.emit("event", {"second": True})
        time.sleep(0.1)

        # Only the first event should be in results (second was ignored)
        assert results == [{"first": True}]

# ----------------------------------------------------------------------------------------------------
    def test_unsubscribe_nonexistent_callback(self):
        """Unsubscribing a callback that was never subscribed should not crash."""
        bus = EventBus()

        def handler():
            pass

        # This handler was never subscribed to "event" — should be silently ignored
        bus.unsubscribe("event", handler)

# ----------------------------------------------------------------------------------------------------
    def test_unsubscribe_nonexistent_event(self):
        """Unsubscribing from an event that doesn't exist should not crash."""
        bus = EventBus()

        def handler():
            pass

        # "never_registered" was never used — should be silently ignored
        bus.unsubscribe("never_registered", handler)

# ----------------------------------------------------------------------------------------------------
    def test_duplicate_subscribe_ignored(self):
        """Subscribing the same callback twice should NOT cause it to be called twice."""
        bus = EventBus()
        results = []

        def handler(data):
            results.append(data)

        bus.subscribe("event", handler)
        bus.subscribe("event", handler)  # Duplicate — should be ignored
        bus.emit("event", {"val": 1})

        time.sleep(0.1)
        # handler should only be called ONCE, not twice
        assert results == [{"val": 1}]


# ----------------------------------------------------------------------------------------------------
class TestEventBusThreadSafety:
    """
    Verify thread-safe operation under concurrent access.

    These tests simulate multiple threads subscribing and emitting at the same time,
    which is what happens in real usage (PIR sensor thread, voice command thread, etc.
    all using the bus simultaneously).
    """

# ----------------------------------------------------------------------------------------------------
    def test_concurrent_subscribe_emit(self):
        """Many threads subscribing and emitting simultaneously should not crash or deadlock."""
        bus = EventBus()
        results = []
        lock = threading.Lock()  # Protect our results list from concurrent writes

        def handler(data):
            # Use a lock when appending because multiple threads call this simultaneously
            with lock:
                results.append(data)

        def subscriber():
            """A function that subscribes to events 50 times."""
            for i in range(50):
                bus.subscribe(f"event_{i % 5}", handler)

        def emitter():
            """A function that emits events 50 times."""
            for i in range(50):
                bus.emit(f"event_{i % 5}", {"i": i})

        # Create 8 threads: 4 subscribing and 4 emitting, all running at the same time
        threads = []
        for _ in range(4):
            threads.append(threading.Thread(target=subscriber))
            threads.append(threading.Thread(target=emitter))

        # Start all threads
        for t in threads:
            t.start()
        # Wait for all threads to finish
        for t in threads:
            t.join()

        # Give callback threads time to complete
        time.sleep(0.5)
        # The main assertion: we completed without crashes or deadlocks,
        # and at least some events were delivered
        assert len(results) > 0

# ----------------------------------------------------------------------------------------------------
    def test_subscriber_exception_does_not_crash_bus(self):
        """If one subscriber raises an exception, other subscribers should still be called."""
        bus = EventBus()
        results = []

        def bad_handler(data):
            # This subscriber is broken — it always crashes
            raise ValueError("I broke!")

        def good_handler(data):
            # This subscriber works fine
            results.append(data)

        # Subscribe both — bad one first
        bus.subscribe("event", bad_handler)
        bus.subscribe("event", good_handler)
        bus.emit("event", {"test": True})

        time.sleep(0.1)
        # Even though bad_handler crashed, good_handler should still have been called.
        # This is critical — one buggy module shouldn't take down the whole system.
        assert results == [{"test": True}]
