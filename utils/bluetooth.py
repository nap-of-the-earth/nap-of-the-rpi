# ----------------------------------------------------------------------------------------------------
# bluetooth.py
# ----------------------------------------------------------------------------------------------------

"""
Bluetooth utility: connection helper for Bluetooth speaker.

Manages connecting to a paired Bluetooth audio device (e.g., JBL Flip 6)
via bluetoothctl subprocess commands. This module handles:
- Checking if a device is currently connected
- Connecting to a paired device
- Retry logic with configurable attempts and delay

Note: This module assumes the device has already been PAIRED (via scripts/pair_bluetooth.sh).
It only handles connecting to already-paired devices.

On Windows (for development), all methods return True (simulating a connected speaker)
since bluetoothctl is Linux-only.
"""

# ----------------------------------------------------------------------------------------------------
import logging
import platform
import subprocess
import time

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------------------------------
class BluetoothHelper:
    """
    Manages Bluetooth speaker connection, reconnection, and status checks.

    Uses bluetoothctl (Linux BlueZ stack) to interact with Bluetooth devices.
    On non-Linux systems, operations are simulated for development purposes.

    Usage:
        bt = BluetoothHelper("JBL Flip 6")
        if bt.ensure_connected():
            print("Speaker ready!")
        else:
            print("Falling back to 3.5mm jack")
    """

    def __init__(self, device_name: str):
        """
        Initialize with the Bluetooth device name.

        Args:
            device_name: The human-readable name of the BT device (e.g., "JBL Flip 6").
        """
        self.device_name = device_name
        self._mac_address: str | None = None  # Cached MAC address
        self._is_linux = platform.system() == "Linux"

    # ------------------------------------------------------------------------------------------------
    def is_connected(self) -> bool:
        """
        Check if the configured Bluetooth device is currently connected.

        Returns:
            True if connected, False otherwise.
        """
        if not self._is_linux:
            # On non-Linux (dev machine), assume connected
            return True

        mac = self._get_mac_address()
        if mac is None:
            return False

        try:
            result = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "Connected: yes" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"Failed to check BT status: {e}")
            return False

    # ------------------------------------------------------------------------------------------------
    def connect(self) -> bool:
        """
        Attempt to connect to the configured Bluetooth device.

        Returns:
            True if connection succeeded, False otherwise.
        """
        if not self._is_linux:
            return True

        mac = self._get_mac_address()
        if mac is None:
            logger.error(f"Cannot find MAC address for '{self.device_name}'")
            return False

        try:
            result = subprocess.run(
                ["bluetoothctl", "connect", mac],
                capture_output=True,
                text=True,
                timeout=10,
            )
            success = "Connection successful" in result.stdout
            if success:
                logger.info(f"Connected to {self.device_name} ({mac})")
            else:
                logger.warning(f"Failed to connect to {self.device_name}: {result.stdout}")
            return success
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"BT connect failed: {e}")
            return False

    # ------------------------------------------------------------------------------------------------
    def ensure_connected(self, retries: int = 3, delay: float = 2.0) -> bool:
        """
        Attempt connection with retries. Returns True if connected.

        First checks if already connected. If not, tries to connect
        up to `retries` times with `delay` seconds between attempts.

        Args:
            retries: Number of connection attempts (default 3).
            delay: Seconds to wait between retries (default 2.0).

        Returns:
            True if the device is connected after attempts, False otherwise.
        """
        # Already connected? Done.
        if self.is_connected():
            return True

        # Try to connect with retries
        for attempt in range(1, retries + 1):
            logger.info(f"BT connect attempt {attempt}/{retries} for '{self.device_name}'")
            if self.connect():
                return True
            if attempt < retries:
                time.sleep(delay)

        logger.error(f"Failed to connect to '{self.device_name}' after {retries} attempts")
        return False

    # ------------------------------------------------------------------------------------------------
    def _get_mac_address(self) -> str | None:
        """
        Look up the MAC address for the configured device name.

        Caches the result after first successful lookup.

        Returns:
            MAC address string (e.g., "AA:BB:CC:DD:EE:FF") or None if not found.
        """
        if self._mac_address is not None:
            return self._mac_address

        try:
            result = subprocess.run(
                ["bluetoothctl", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Output format: "Device AA:BB:CC:DD:EE:FF JBL Flip 6"
            for line in result.stdout.splitlines():
                if self.device_name.lower() in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        self._mac_address = parts[1]
                        return self._mac_address
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"Failed to list BT devices: {e}")

        return None
