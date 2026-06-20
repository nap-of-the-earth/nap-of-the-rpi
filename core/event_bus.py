# ----------------------------------------------------------------------------------------------------
# event_bus.py
# ----------------------------------------------------------------------------------------------------

"""
Event bus: lightweight pub/sub for inter-module communication.

Think of it like a radio station:
- Modules "tune in" (subscribe) to specific channels (event names)
- When something happens, a module "broadcasts" (emit) on a channel
- Everyone tuned into that channel hears the message
- This way, modules don't need to know about each other directly
"""

# ----------------------------------------------------------------------------------------------------
# contextlib.suppress — a cleaner way to ignore specific exceptions
# threading — Python's built-in library for running code in parallel
import contextlib
import threading


class EventBus:
    """
    Thread-safe publish/subscribe event system.

    Provides decoupled communication between modules. Subscribers register
    callbacks for named events; emitters fire events without knowledge of
    who is listening.

    Usage example:
        bus = EventBus()

        # Module A subscribes to an event
        def on_human_detected(data):
            print(f"Human detected at {data['timestamp']}")

        bus.subscribe("human_detected", on_human_detected)

        # Module B emits that event later
        bus.emit("human_detected", {"timestamp": "12:00"})
        # -> on_human_detected gets called automatically
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self):
        # Dictionary mapping event names to lists of callback functions.
        # Example: {"human_detected": [func1, func2], "laser_off": [func3]}
        self._subscribers: dict[str, list] = {}

        # A lock prevents two threads from modifying _subscribers at the same time.
        # Without this, concurrent subscribe/emit calls could corrupt the dictionary.
        # "with self._lock:" means "wait your turn, only one thread at a time in this block"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------------------
    def subscribe(self, event_name: str, callback) -> None:
        """
        Register a callback for an event.

        Args:
            event_name: Name of the event to listen for (e.g., "human_detected").
            callback: A function to call when the event fires.
                      It receives an optional data dict as its argument.
        """
        # Acquire the lock so no other thread can modify _subscribers while we're adding
        with self._lock:
            # If this event hasn't been registered before, create an empty list for it
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            # Only add the callback if it's not already subscribed (prevent duplicates)
            if callback not in self._subscribers[event_name]:
                self._subscribers[event_name].append(callback)

    # ------------------------------------------------------------------------------------------------
    def emit(self, event_name: str, data: dict | None = None) -> None:
        """
        Emit an event to all subscribers.

        Each callback runs in its own thread so the emitter doesn't have to wait
        for subscribers to finish. This is important because:
        - The PIR sensor shouldn't wait for a weather API call to complete
        - A slow TTS announcement shouldn't block the next detection

        Args:
            event_name: Name of the event to emit (e.g., "human_detected").
            data: Optional dict of event data passed to each callback.
        """
        # Grab a snapshot of current subscribers while holding the lock.
        # list(...) creates a COPY so we're safe even if someone subscribes/unsubscribes
        # while we're iterating.
        with self._lock:
            callbacks = list(self._subscribers.get(event_name, []))

        # For each subscriber, start a new background thread to run their callback.
        # daemon=True means these threads will be killed when the main program exits
        # (they won't keep the app running forever if something hangs).
        for callback in callbacks:
            threading.Thread(
                target=self._safe_call,  # The function to run in the new thread
                args=(callback, data),   # Arguments to pass to that function
                daemon=True,             # Thread dies when main program exits
            ).start()

    # ------------------------------------------------------------------------------------------------
    def unsubscribe(self, event_name: str, callback) -> None:
        """
        Remove a callback from an event.

        After this, the callback will no longer be called when the event fires.

        Args:
            event_name: Name of the event to unsubscribe from.
            callback: The callback function to remove.
        """
        with self._lock:
            if event_name in self._subscribers:
                # contextlib.suppress(ValueError) means:
                # "try to remove it, but if it's not in the list, don't crash"
                # This is cleaner than try/except ValueError: pass
                with contextlib.suppress(ValueError):
                    self._subscribers[event_name].remove(callback)

    # ------------------------------------------------------------------------------------------------
    @staticmethod
    def _safe_call(callback, data: dict | None) -> None:
        """
        Invoke a callback, catching and logging exceptions.

        This is marked @staticmethod because it doesn't need access to 'self'
        (it doesn't read or write any instance variables). It's just a helper
        function that lives inside the class for organization.

        Why "safe"? Because if a subscriber's callback crashes (raises an exception),
        we catch it and print an error instead of letting it kill the thread or
        affect other subscribers. One broken module shouldn't take down the whole system.
        """
        try:
            # If event was emitted with data, pass it to the callback
            if data is not None:
                callback(data)
            else:
                # If no data was provided, call with no arguments.
                # This lets callbacks optionally accept data or not:
                #   def on_ping():         # No data expected
                #   def on_detect(data):   # Data expected
                callback()
        except Exception as e:
            # callback.__name__ gives us the function's name (e.g., "on_human_detected")
            # This helps us identify WHICH subscriber crashed when debugging
            print(f"[EventBus] Error in subscriber {callback.__name__}: {e}")
