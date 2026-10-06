"""
Windows RFCOMM Manager for MW75 EEG Streamer

Implements the RFCOMM data link on Windows using the Python standard library's
``AF_BTH`` / ``BTPROTO_RFCOMM`` socket support (Winsock Bluetooth). This mirrors
the macOS ``RFCOMMManager`` (PyObjC/IOBluetooth) and the Linux
``LinuxRFCOMMManager`` (BlueZ) so the rest of the pipeline is unchanged:
``connect()`` -> ``run_until_stopped()`` -> ``stop()`` / ``close()``. Raw bytes
are delivered to ``data_callback`` as they arrive; framing into 63-byte packets
happens downstream in ``PacketProcessor``.

Address resolution (v1): the paired MW75's Bluetooth **Classic** address is taken
from the ``MW75_BT_ADDR`` environment variable — the same override the macOS and
Linux backends accept. Automatic enumeration of paired devices via the Win32
Bluetooth API (``BluetoothFindFirstDevice``) is a deliberate follow-up: it needs
validation on real Windows hardware, which this build environment does not have.
Until then, Windows users supply the address explicitly (see ``README_WINDOWS.md``).

STATUS — NOT hardware-verified. The constellation build env has no Windows box or
MW75 headset, so the on-device 500 Hz / 12-channel stream is unverified. The
machine-checkable parts (factory selection, address formatting, import invariants,
static analysis) are covered by CI; the live stream is pending owner verification,
exactly as the Linux port (PR #1) is. Do not report Windows streaming as confirmed.
"""

import os
import socket
from typing import Callable, Optional

from ..config import RFCOMM_CHANNEL, RFCOMM_CONNECTION_TIMEOUT
from ..utils.logging import get_logger

# Explicit Bluetooth Classic address of the paired MW75, e.g. "AA:BB:CC:DD:EE:FF".
# Required on Windows in v1 (see module docstring). Shared name with the Linux
# backend so the override is identical across platforms.
BT_ADDR_ENV_VAR = "MW75_BT_ADDR"

# How long the blocking recv() waits before re-checking the stop flag.
_RECV_TIMEOUT = 1.0
# Size of each recv() chunk. Raw bytes are framed downstream by PacketProcessor.
_RECV_BUFSIZE = 4096


class WindowsRFCOMMManager:
    """Manages the RFCOMM connection and data streaming on Windows via Winsock."""

    def __init__(self, device_name: str, data_callback: Callable[[bytes], None]) -> None:
        """
        Initialize the Windows RFCOMM manager.

        Args:
            device_name: Name of the MW75 device (informational in v1; the address
                comes from ``MW75_BT_ADDR``).
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
        Resolve the paired device address and open RFCOMM channel 25.

        Returns:
            True if the connection was established, False otherwise.
        """
        if not hasattr(socket, "AF_BTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
            self.logger.error(
                "This Python build lacks AF_BTH/BTPROTO_RFCOMM socket support; "
                "cannot open an RFCOMM channel on Windows."
            )
            return False

        address = self._resolve_device_address()
        if not address:
            return False

        self.device_address = address
        return self._open_channel(address)

    def _resolve_device_address(self) -> Optional[str]:
        """Resolve the Bluetooth Classic address of the paired MW75.

        v1 uses the ``MW75_BT_ADDR`` override exclusively (Win32 enumeration is a
        follow-up). Returns None with actionable guidance when it is unset.
        """
        override = os.environ.get(BT_ADDR_ENV_VAR)
        if override:
            self.logger.info(f"Using Bluetooth address from {BT_ADDR_ENV_VAR}: {override}")
            return override.strip()

        self.logger.error(
            f"No Bluetooth address provided. On Windows, set {BT_ADDR_ENV_VAR} to the "
            f"paired MW75's Classic address, e.g.  set {BT_ADDR_ENV_VAR}=AA:BB:CC:DD:EE:FF"
        )
        self.logger.info(
            "Find it in Settings > Bluetooth & devices (device properties), or with "
            "PowerShell:  Get-PnpDevice -Class Bluetooth | Format-List FriendlyName,InstanceId"
        )
        return None

    def _open_channel(self, address: str) -> bool:
        """Open an RFCOMM socket to ``address`` on the EEG channel."""
        bth_addr = self._to_bth_address(address)
        self.logger.info(f"Connecting RFCOMM to {self.device_name} ({bth_addr}) ...")
        sock: Optional[socket.socket] = None
        try:
            # AF_BTH / BTPROTO_RFCOMM are Windows-only and absent from some typeshed
            # versions; access them dynamically (guarded by the hasattr in connect()).
            af_bth = getattr(socket, "AF_BTH")
            btproto_rfcomm = getattr(socket, "BTPROTO_RFCOMM")
            sock = socket.socket(af_bth, socket.SOCK_STREAM, btproto_rfcomm)
            sock.settimeout(RFCOMM_CONNECTION_TIMEOUT)
            # Winsock AF_BTH connect address is (address_string, channel).
            sock.connect((bth_addr, RFCOMM_CHANNEL))
            # Switch to a short read timeout so the loop can poll the stop flag.
            sock.settimeout(_RECV_TIMEOUT)
        except OSError as e:
            self.logger.error(f"RFCOMM connection failed: {e}")
            self.logger.info(
                "Ensure the MW75 is paired in Windows Bluetooth settings and that "
                f"{BT_ADDR_ENV_VAR} matches its address."
            )
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

    @staticmethod
    def _to_bth_address(address: str) -> str:
        """Normalise a Bluetooth address for the Winsock AF_BTH sockaddr.

        Winsock resolves AF_BTH address strings via ``WSAStringToAddress``, which
        expects the parenthesised form ``(AA:BB:CC:DD:EE:FF)``. Accept either the
        bare or parenthesised form from the user and return the parenthesised one.
        """
        addr = address.strip()
        if not addr.startswith("("):
            addr = f"({addr}"
        if not addr.endswith(")"):
            addr = f"{addr})"
        return addr

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
