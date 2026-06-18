# ----------------------------------------------------------------------------------------------------
# event_bus.py
# ----------------------------------------------------------------------------------------------------

"""
Event bus: lightweight pub/sub for inter-module communication.
"""

# ----------------------------------------------------------------------------------------------------
import contextlib
import threading


class EventBus:
    """
    Thread-safe publish/subscribe event system.

    Provides decoupled communication between modules. Subscribers register
    callbacks for named events; emitters fire events without knowledge of
    who is listening.
    """

    # ------------------------------------------------------------------------------------------------
    def __init__(self):
        self._subscribers: dict[str, list] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------------------
    def subscribe(self, event_name: str, callback) -> None:
        """
        Register a callback for an event.

        Args:
            event_name: Name of the event to listen for.
            callback: Callable to invoke when the event is emitted.
                      Receives an optional data dict as its argument.
        """
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            if callback not in self._subscribers[event_name]:
                self._subscribers[event_name].append(callback)

    # ------------------------------------------------------------------------------------------------
    def emit(self, event_name: str, data: dict | None = None) -> None:
        """
        Emit an event to all subscribers.

        Callbacks are invoked in a separate thread to avoid blocking the emitter.

        Args:
            event_name: Name of the event to emit.
            data: Optional dict of event data passed to each callback.
        """
        with self._lock:
            callbacks = list(self._subscribers.get(event_name, []))

        for callback in callbacks:
            threading.Thread(
                target=self._safe_call,
                args=(callback, data),
                daemon=True,
            ).start()

    # ------------------------------------------------------------------------------------------------
    def unsubscribe(self, event_name: str, callback) -> None:
        """
        Remove a callback from an event.

        Args:
            event_name: Name of the event to unsubscribe from.
            callback: The callback to remove.
        """
        with self._lock:
            if event_name in self._subscribers:
                with contextlib.suppress(ValueError):
                    self._subscribers[event_name].remove(callback)

    # ------------------------------------------------------------------------------------------------
    @staticmethod
    def _safe_call(callback, data: dict | None) -> None:
        """
        Invoke a callback, catching and logging exceptions.
        """
        try:
            if data is not None:
                callback(data)
            else:
                callback()
        except Exception as e:
            # Avoid crashing the bus if a subscriber raises
            print(f"[EventBus] Error in subscriber {callback.__name__}: {e}")
