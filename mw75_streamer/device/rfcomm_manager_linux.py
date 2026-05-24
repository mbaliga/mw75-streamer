"""
Linux RFCOMM Manager for MW75 EEG Streamer

Implements the RFCOMM data link on Linux using the Python standard library's
``AF_BLUETOOTH`` / ``BTPROTO_RFCOMM`` socket support (backed by BlueZ). The
paired device's Bluetooth Classic address is resolved from BlueZ over D-Bus via
``dbus-fast`` (already a transitive dependency of ``bleak`` on Linux), mirroring
the macOS ``IOBluetoothDevice.pairedDevices()`` lookup by name.

The public interface matches the macOS ``RFCOMMManager`` and the
``MockRFCOMMManager`` so the rest of the pipeline is unchanged:
``connect()`` -> ``run_until_stopped()`` -> ``stop()`` / ``close()``. Raw bytes
are delivered to ``data_callback`` as they arrive; framing into 63-byte packets
happens downstream in ``PacketProcessor``.
"""

import asyncio
import os
import socket
import threading
from typing import Any, Callable, List, Optional, cast

from ..config import RFCOMM_CHANNEL, RFCOMM_CONNECTION_TIMEOUT
from ..utils.logging import get_logger

# When set, overrides BlueZ name resolution with an explicit Bluetooth Classic
# address (e.g. "AA:BB:CC:DD:EE:FF"). Useful when the device name cannot be
# resolved over D-Bus, or to pin a specific headset.
BT_ADDR_ENV_VAR = "MW75_BT_ADDR"

# How long the blocking recv() waits before re-checking the stop flag.
_RECV_TIMEOUT = 1.0
# Size of each recv() chunk. Raw bytes are framed downstream by PacketProcessor.
_RECV_BUFSIZE = 4096


class LinuxRFCOMMManager:
    """Manages the RFCOMM connection and data streaming on Linux via BlueZ."""

    def __init__(self, device_name: str, data_callback: Callable[[bytes], None]) -> None:
        """
        Initialize the Linux RFCOMM manager.

        Args:
            device_name: Name of the MW75 device to connect to.
            data_callback: Function to call when data is received.
        """
        self.device_name = device_name
        self.data_callback = data_callback
        self.connected = False
        self.should_stop = False
        self.device_address: Optional[str] = None
        self._sock: Optional[socket.socket] = None
        self.logger = get_logger(__name__)

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        """
        Resolve the paired device and open RFCOMM channel 25.

        Returns:
            True if the connection was established, False otherwise.
        """
        if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
            self.logger.error(
                "This Python build lacks AF_BLUETOOTH/BTPROTO_RFCOMM socket support; "
                "cannot open an RFCOMM channel on Linux."
            )
            return False

        address = self._resolve_device_address()
        if not address:
            return False

        self.device_address = address
        return self._open_channel(address)

    def _resolve_device_address(self) -> Optional[str]:
        """Resolve the Bluetooth Classic address of the paired MW75."""
        override = os.environ.get(BT_ADDR_ENV_VAR)
        if override:
            self.logger.info(f"Using Bluetooth address from {BT_ADDR_ENV_VAR}: {override}")
            return override.strip()

        self.logger.info(f"Looking for paired Bluetooth device: {self.device_name}")
        try:
            address = self._lookup_paired_address_via_bluez(self.device_name)
        except Exception as e:
            self.logger.error(f"Failed to query BlueZ for paired devices: {e}")
            self.logger.info(f"Tip: set {BT_ADDR_ENV_VAR}=<bd_addr> to bypass BlueZ resolution.")
            return None

        if not address:
            self.logger.error(f"No paired device found matching '{self.device_name}'")
            self.logger.info("Please ensure the MW75 is paired (e.g. via 'bluetoothctl').")
            return None

        self.logger.info(f"Found matching paired device: {self.device_name} ({address})")
        return address

    def _open_channel(self, address: str) -> bool:
        """Open an RFCOMM socket to ``address`` on the EEG channel."""
        self.logger.info(f"Connecting RFCOMM to {self.device_name} ({address}) ...")
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(RFCOMM_CONNECTION_TIMEOUT)
            sock.connect((address, RFCOMM_CHANNEL))
            # Switch to a short read timeout so the loop can poll the stop flag.
            sock.settimeout(_RECV_TIMEOUT)
        except OSError as e:
            self.logger.error(f"RFCOMM connection failed: {e}")
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            return False

        self._sock = sock
        self.connected = True
        self.logger.info("RFCOMM connected - data is flowing!")
        return True

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #

    def run_until_stopped(self) -> None:
        """Blocking read loop; forwards each chunk to ``data_callback``."""
        if not self.connected or self._sock is None:
            self.logger.error("Cannot run - RFCOMM not connected")
            return

        self.logger.info("Data streaming... Press Ctrl+C to stop")
        sock = self._sock

        while not self.should_stop:
            try:
                data = sock.recv(_RECV_BUFSIZE)
            except socket.timeout:
                # No data within the poll window - re-check the stop flag.
                continue
            except OSError as e:
                if self.should_stop:
                    break
                self.logger.error(f"RFCOMM read error: {e}")
                break

            if not data:
                # Zero-length read means the peer closed the channel.
                self.logger.info("RFCOMM channel closed by device")
                self.connected = False
                break

            try:
                self.data_callback(data)
            except Exception as e:
                self.logger.error(f"Error processing RFCOMM data: {e}")

    def stop(self) -> None:
        """Signal the read loop to stop and interrupt a blocking recv()."""
        self.logger.info("Stop requested for RFCOMM read loop")
        self.should_stop = True
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                # Already closed or never fully connected; the timeout will catch it.
                pass

    def close(self) -> None:
        """Close the RFCOMM socket and reset state for potential reuse."""
        if self._sock is not None:
            try:
                self.logger.info("Closing RFCOMM channel...")
                self._sock.close()
                self.logger.info("RFCOMM channel closed")
            except OSError as e:
                self.logger.error(f"Error closing RFCOMM: {e}")
            finally:
                self._sock = None
        else:
            self.logger.debug("No RFCOMM channel to close")

        self.connected = False
        self.should_stop = False

    # ------------------------------------------------------------------ #
    # BlueZ address resolution (D-Bus)
    # ------------------------------------------------------------------ #

    def _lookup_paired_address_via_bluez(self, name: str) -> Optional[str]:
        """Look up the Classic address of a paired device by name via BlueZ."""
        return cast(
            Optional[str],
            self._run_coroutine_in_thread(lambda: self._async_lookup(name)),
        )

    async def _async_lookup(self, name: str) -> Optional[str]:
        """Query BlueZ's object manager for a paired device matching ``name``."""
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            introspection = await bus.introspect("org.bluez", "/")
            root = bus.get_proxy_object("org.bluez", "/", introspection)
            # dbus-fast generates call_* methods dynamically from introspection,
            # so they are not visible to the static type checker.
            manager: Any = root.get_interface("org.freedesktop.DBus.ObjectManager")
            objects = await manager.call_get_managed_objects()
        finally:
            bus.disconnect()

        target = name.upper()
        paired_match: Optional[str] = None
        unpaired_match: Optional[str] = None

        for _path, interfaces in objects.items():
            device = interfaces.get("org.bluez.Device1")
            if not device:
                continue

            address = self._variant_value(device.get("Address"))
            dev_name = self._variant_value(device.get("Name")) or self._variant_value(
                device.get("Alias")
            )
            paired = bool(self._variant_value(device.get("Paired")))
            if not address or not dev_name:
                continue

            if target in str(dev_name).upper():
                if paired and paired_match is None:
                    paired_match = str(address)
                elif not paired and unpaired_match is None:
                    unpaired_match = str(address)

        if paired_match:
            return paired_match
        if unpaired_match:
            self.logger.warning(
                f"Found '{self.device_name}' in BlueZ but it is not marked paired; "
                "attempting to connect anyway."
            )
            return unpaired_match
        return None

    @staticmethod
    def _variant_value(variant: Any) -> Any:
        """Unwrap a dbus-fast ``Variant`` (or pass the value through)."""
        if variant is None:
            return None
        return getattr(variant, "value", variant)

    @staticmethod
    def _run_coroutine_in_thread(coro_factory: Callable[[], Any]) -> Any:
        """Run an async coroutine to completion on a private loop in a thread.

        ``connect()`` is called synchronously from within the already-running
        asyncio event loop (``MW75Device.connect_and_stream``), so a new loop
        cannot be started on this thread. A dedicated thread with its own event
        loop keeps the async D-Bus query isolated.
        """
        box: List[Any] = []
        err: List[BaseException] = []

        def _runner() -> None:
            try:
                box.append(asyncio.run(coro_factory()))
            except BaseException as exc:  # re-raised in the caller's thread
                err.append(exc)

        thread = threading.Thread(target=_runner, name="MW75-BlueZ", daemon=True)
        thread.start()
        thread.join()

        if err:
            raise err[0]
        return box[0] if box else None
