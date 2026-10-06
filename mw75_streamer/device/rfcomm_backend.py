"""
RFCOMM backend factory for the MW75 EEG Streamer.

Selects the platform-appropriate RFCOMM manager implementation at runtime and
imports it lazily, so platform-specific dependencies are only imported on the
platform that actually uses them (PyObjC/IOBluetooth on macOS, BlueZ/dbus-fast
on Linux). This keeps ``mw75_device`` importable on every platform.

All RFCOMM manager implementations share the structural interface described by
``RFCOMMManagerProtocol``: the macOS ``RFCOMMManager``, the Linux
``LinuxRFCOMMManager`` and the cross-platform ``MockRFCOMMManager``.
"""

import sys
from typing import Callable, Optional, Protocol


class RFCOMMManagerProtocol(Protocol):
    """Structural interface implemented by every RFCOMM manager."""

    device_address: Optional[str]
    connected: bool
    should_stop: bool

    def connect(self) -> bool:
        """Find the paired device and open the RFCOMM channel."""
        ...

    def run_until_stopped(self) -> None:
        """Blocking read loop; forwards raw bytes to the data callback."""
        ...

    def stop(self) -> None:
        """Signal the read loop to stop."""
        ...

    def close(self) -> None:
        """Tear down the RFCOMM channel and release resources."""
        ...


def create_rfcomm_manager(
    device_name: str, data_callback: Callable[[bytes], None]
) -> RFCOMMManagerProtocol:
    """Create the RFCOMM manager for the current platform.

    Args:
        device_name: Name (or name substring) of the paired MW75 device.
        data_callback: Called with each chunk of raw bytes as it arrives.

    Returns:
        A platform-specific manager implementing ``RFCOMMManagerProtocol``.

    Raises:
        RuntimeError: If the current platform has no real-device RFCOMM backend.
    """
    if sys.platform == "darwin":
        from .rfcomm_manager import RFCOMMManager

        return RFCOMMManager(device_name, data_callback)

    if sys.platform == "linux":
        from .rfcomm_manager_linux import LinuxRFCOMMManager

        return LinuxRFCOMMManager(device_name, data_callback)

    raise RuntimeError(
        f"No RFCOMM backend available for platform '{sys.platform}'. "
        "Real-device streaming is supported on macOS and Linux; "
        "use --mock for cross-platform development."
    )
