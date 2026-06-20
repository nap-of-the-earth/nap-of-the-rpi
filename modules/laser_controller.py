# ----------------------------------------------------------------------------------------------------
# laser_controller.py
# ----------------------------------------------------------------------------------------------------

"""
Laser controller module: drives KY-008 laser with configurable patterns.

The KY-008 is a simple 650nm red laser diode module. It's controlled by a single GPIO pin — HIGH turns
it on, LOW turns it off. For the "pulse" pattern, we use PWM (Pulse Width Modulation) to smoothly vary
the brightness.

This module subscribes to events and activates the laser with the configured pattern when a human is
detected or a voice command enables it.
"""

# ----------------------------------------------------------------------------------------------------
from gpiozero import PWMLED

# ----------------------------------------------------------------------------------------------------
import logging
import threading
import time

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------------------
class LaserController:
    """
    Controls KY-008 laser module via GPIO with configurable patterns.

    Supports three activation patterns:
    - solid: Laser stays ON for a set duration, then turns OFF
    - blink: Laser toggles ON/OFF at a configurable frequency
    - pulse: Laser fades in/out using PWM (Pulse Width Modulation)

    Safety: The laser ALWAYS turns off after the configured duration expires,
    and is forced off on stop() even if a pattern is mid-execution.

    Hardware wiring:
        KY-008 Signal → Pi GPIO 18 (via 220Ω resistor)
        KY-008 VCC    → Pi 5V
        KY-008 GND    → Pi GND

    Usage:
        laser = LaserController(event_bus, config)
        laser.start()           # Subscribes to events, ready to fire
        laser.activate()        # Manually trigger current pattern
        laser.set_pattern("pulse")  # Change pattern without restart
        laser.stop()            # Ensure laser off, clean up
    """

# ----------------------------------------------------------------------------------------------------
    def __init__(self, event_bus, config):
        """
        Initialize the laser controller.

        Args:
            event_bus: The EventBus instance for subscribing to trigger events.
            config: The Config instance (uses config.laser.*).
        """
        self.event_bus = event_bus
        self.config = config

        # Internal state
        self._laser: PWMLED | None = None           # gpiozero PWMLED instance (created on start)
        self._running = False                       # Whether the controller is active
        self._pattern_thread: threading.Thread | None = None  # Background thread running current pattern
        self._cancel_event = threading.Event()      # Signal to stop a running pattern
        self._enabled = True                        # Can be disabled via 'command_laser_off'

# ----------------------------------------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        """
        Whether the laser is currently executing a pattern.
        """
        return self._pattern_thread is not None and self._pattern_thread.is_alive()

# ----------------------------------------------------------------------------------------------------
    def start(self) -> None:
        """
        Initialize GPIO and subscribe to events.

        Subscribes to:
        - 'human_detected': triggers the laser pattern
        - 'command_laser_on': re-enables the laser
        - 'command_laser_off': disables the laser (and stops current pattern)
        """
        if self._running:
            logger.warning("Laser controller already running")
            return

        pin = self.config.laser.pin

        try:
            # PWMLED allows both on/off AND brightness control (0.0 to 1.0).
            # We need PWM for the "pulse" pattern (smooth fade in/out).
            # For "solid" and "blink" we just use value=1.0 or value=0.0.
            laser = PWMLED(pin)
            laser.off()  # Start with laser OFF (safety)
            self._laser = laser

            # Subscribe to events
            self.event_bus.subscribe("human_detected", self._on_human_detected)
            self.event_bus.subscribe("command_laser_on", self._on_laser_on)
            self.event_bus.subscribe("command_laser_off", self._on_laser_off)

            self._running = True
            logger.info(f"Laser controller started on GPIO {pin}")

        except Exception as e:
            logger.error(f"Failed to start laser controller: {e}")
            self.event_bus.emit("error", {
                "module": "laser_controller",
                "message": f"Failed to initialize: {e}",
            })

# ----------------------------------------------------------------------------------------------------
    def stop(self) -> None:
        """
        Stop the laser controller. Ensures laser is OFF and releases GPIO.

        IMPORTANT: This guarantees the laser is turned off even if a pattern
        is currently running. Safety first.
        """
        self._running = False

        # Cancel any running pattern
        self._cancel_event.set()
        if self._pattern_thread is not None:
            self._pattern_thread.join(timeout=2.0)
            self._pattern_thread = None

        # Force laser off and release GPIO
        if self._laser is not None:
            try:
                self._laser.off()
                self._laser.close()
            except Exception as e:
                logger.error(f"Error closing laser: {e}")
            self._laser = None

        logger.info("Laser controller stopped")

# ----------------------------------------------------------------------------------------------------
    def set_pattern(self, pattern: str) -> None:
        """
        Change the active laser pattern.

        Valid patterns: "solid", "blink", "pulse"
        Takes effect on the next activation (doesn't restart a current pattern).

        Args:
            pattern: One of "solid", "blink", "pulse"
        """
        valid_patterns = ("solid", "blink", "pulse")
        if pattern not in valid_patterns:
            logger.warning(f"Invalid pattern '{pattern}', must be one of {valid_patterns}")
            return
        self.config.laser.pattern = pattern
        logger.info(f"Laser pattern changed to: {pattern}")

# ----------------------------------------------------------------------------------------------------
    def activate(self) -> None:
        """
        Trigger the laser with the current pattern.

        If a pattern is already running, it's cancelled first.
        If the laser is disabled (via 'command_laser_off'), this does nothing.
        """
        if not self._running or not self._enabled:
            return

        # Cancel any currently running pattern
        if self.is_active and self._pattern_thread is not None:
            self._cancel_event.set()
            self._pattern_thread.join(timeout=2.0)

        # Reset cancel event and start new pattern in background thread
        self._cancel_event.clear()
        pattern = self.config.laser.pattern
        duration = self.config.laser.duration_seconds

        self._pattern_thread = threading.Thread(
            target=self._run_pattern,
            args=(pattern, duration),
            daemon=True,
        )
        self._pattern_thread.start()

# ----------------------------------------------------------------------------------------------------
    def deactivate(self) -> None:
        """Force the laser off immediately, cancelling any running pattern."""
        self._cancel_event.set()
        if self._laser is not None:
            self._laser.off()

# ----------------------------------------------------------------------------------------------------
    def _on_human_detected(self, data=None) -> None:
        """Event handler: activate laser when human is detected."""
        if self._enabled:
            logger.info("Human detected — activating laser")
            self.activate()

# ----------------------------------------------------------------------------------------------------
    def _on_laser_on(self, data=None) -> None:
        """Event handler: re-enable the laser."""
        self._enabled = True
        logger.info("Laser enabled via command")

# ----------------------------------------------------------------------------------------------------
    def _on_laser_off(self, data=None) -> None:
        """Event handler: disable the laser and stop current pattern."""
        self._enabled = False
        self.deactivate()
        logger.info("Laser disabled via command")

# ----------------------------------------------------------------------------------------------------
    def _run_pattern(self, pattern: str, duration: float) -> None:
        """
        Execute a laser pattern for the given duration.

        Runs in a background thread. Monitors _cancel_event to stop early.
        ALWAYS turns off the laser when done (try/finally for safety).

        Args:
            pattern: "solid", "blink", or "pulse"
            duration: How long the pattern runs (seconds)
        """
        try:
            if pattern == "solid":
                self._pattern_solid(duration)
            elif pattern == "blink":
                self._pattern_blink(duration)
            elif pattern == "pulse":
                self._pattern_pulse(duration)
        except Exception as e:
            logger.error(f"Error during laser pattern '{pattern}': {e}")
        finally:
            # SAFETY: Always turn off the laser when pattern ends
            if self._laser is not None:
                self._laser.off()

# ----------------------------------------------------------------------------------------------------
    def _pattern_solid(self, duration: float) -> None:
        """Solid pattern: laser ON for duration, then OFF."""
        if self._laser is None:
            return
        self._laser.on()
        # Wait for duration OR until cancelled (whichever comes first)
        self._cancel_event.wait(timeout=duration)

# ----------------------------------------------------------------------------------------------------
    def _pattern_blink(self, duration: float) -> None:
        """Blink pattern: toggle laser at configured frequency."""
        if self._laser is None:
            return

        frequency = self.config.laser.blink_frequency_hz
        # Period = time for one full on/off cycle
        period = 1.0 / frequency
        half_period = period / 2.0

        end_time = time.time() + duration
        while time.time() < end_time and not self._cancel_event.is_set():
            self._laser.on()
            if self._cancel_event.wait(timeout=half_period):
                break
            self._laser.off()
            if self._cancel_event.wait(timeout=half_period):
                break

# ----------------------------------------------------------------------------------------------------
    def _pattern_pulse(self, duration: float) -> None:
        """Pulse pattern: smooth fade in/out using PWM."""
        if self._laser is None:
            return

        pulse_rate = self.config.laser.pulse_rate_hz
        # One full pulse cycle (fade in + fade out) takes 1/pulse_rate seconds
        cycle_time = 1.0 / pulse_rate
        steps = 50  # Number of brightness steps per half-cycle
        step_time = cycle_time / (steps * 2)

        end_time = time.time() + duration
        while time.time() < end_time and not self._cancel_event.is_set():
            # Fade in: 0.0 → 1.0
            for i in range(steps):
                if self._cancel_event.is_set():
                    return
                self._laser.value = i / steps
                time.sleep(step_time)
            # Fade out: 1.0 → 0.0
            for i in range(steps, 0, -1):
                if self._cancel_event.is_set():
                    return
                self._laser.value = i / steps
                time.sleep(step_time)
