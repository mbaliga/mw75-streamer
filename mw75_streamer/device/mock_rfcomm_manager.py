"""
Mock RFCOMM Manager for MW75 EEG Streamer

Provides a mock RFCOMM manager for development without physical hardware.
Generates valid 63-byte EEG packets at ~500Hz with realistic random data.
"""

import random
import struct
import threading
import time
from typing import Callable, Optional

from ..config import EEG_EVENT_ID, NUM_EEG_CHANNELS, PACKET_SIZE, SYNC_BYTE
from ..utils.logging import get_logger


def build_eeg_packet(counter: int) -> bytes:
    """
    Build a complete 63-byte EEG packet with valid checksum

    Generates a packet with:
    - Valid header (sync byte, event ID, data length, counter)
    - Random REF/DRL values (-50 to +50 µV)
    - Random EEG channel data (raw ADC: -8000 to +8000)
    - Valid checksum

    Args:
        counter: Packet counter (0-255)

    Returns:
        63-byte packet as bytes
    """
    packet = bytearray(PACKET_SIZE)

    # Header
    packet[0] = SYNC_BYTE  # 0xAA
    packet[1] = EEG_EVENT_ID  # 239
    packet[2] = 0x3C  # Data length (60 bytes)
    packet[3] = counter & 0xFF  # Counter (0-255, wrapping)

    # REF and DRL values (already in microvolts)
    # These are typically small values representing reference electrodes
    struct.pack_into("<f", packet, 4, random.uniform(-50.0, 50.0))  # REF
    struct.pack_into("<f", packet, 8, random.uniform(-50.0, 50.0))  # DRL

    # 12 EEG channels (raw ADC values)
    # Will be converted to µV by PacketProcessor using EEG_SCALING_FACTOR (0.023842)
    # Target range after conversion: -200 to +200 µV
    # So raw ADC range: -200/0.023842 to +200/0.023842 ≈ -8391 to +8391
    for ch in range(NUM_EEG_CHANNELS):
        offset = 12 + (ch * 4)
        raw_adc = random.uniform(-8000.0, 8000.0)
        struct.pack_into("<f", packet, offset, raw_adc)

    # Feature status
    packet[60] = 0x00

    # Calculate and pack checksum (sum of first 61 bytes, 16-bit little-endian)
    checksum = sum(packet[:61]) & 0xFFFF
    packet[61] = checksum & 0xFF
    packet[62] = (checksum >> 8) & 0xFF

    return bytes(packet)


class MockRFCOMMManager:
    """
    Mock RFCOMM manager for development without physical hardware

    Provides the same interface as RFCOMMManager but generates synthetic
    EEG data instead of reading from a physical device. Useful for:
    - Cross-platform development (no macOS/IOBluetooth dependency)
    - Testing the data processing pipeline
    - Development without physical MW75 hardware
    """

    def __init__(self, device_name: str, data_callback: Callable[[bytes], None]):
        """
        Initialize mock RFCOMM manager

        Args:
            device_name: Name of the device (ignored in mock, used for logging)
            data_callback: Function to call when data is generated
        """
        self.device_name = device_name
        self.data_callback = data_callback
        self.connected = False
        self.should_stop = False
        self.counter = 0
        self.streaming_thread: Optional[threading.Thread] = None
        self.logger = get_logger(__name__)

    def connect(self) -> bool:
        """
        Simulate RFCOMM connection

        Returns:
            True (always succeeds for mock)
        """
        self.logger.info(f"Mock RFCOMM connecting to {self.device_name}...")
        self.connected = True
        self.logger.info("Mock RFCOMM connected successfully")
        return True

    def _streaming_loop(self) -> None:
        """
        Generate EEG packets at ~500Hz (2ms intervals)

        Uses precise timing with perf_counter and dynamic sleep adjustment
        to maintain consistent packet rate.
        """
        target_interval = 0.002  # 2 milliseconds = 500 Hz
        self.logger.info("Mock streaming loop started (target: 500 Hz)")

        packet_count = 0
        start_time = time.perf_counter()

        while not self.should_stop:
            loop_start = time.perf_counter()

            # Generate and send packet
            packet = build_eeg_packet(self.counter)
            self.data_callback(packet)

            # Increment counter (wraps at 256)
            self.counter = (self.counter + 1) % 256
            packet_count += 1

            # Log statistics every 5 seconds
            if packet_count % 2500 == 0:  # 2500 packets ≈ 5 seconds at 500Hz
                elapsed = time.perf_counter() - start_time
                actual_rate = packet_count / elapsed
                self.logger.debug(
                    f"Mock streaming: {packet_count} packets, " f"actual rate: {actual_rate:.1f} Hz"
                )

            # Sleep for remainder of interval
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(0, target_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def run_until_stopped(self) -> None:
        """
        Run the mock streaming loop (blocking)

        Starts a daemon thread that generates packets and blocks until
        stop() is called or KeyboardInterrupt is received.

        This matches the interface of the real RFCOMMManager.run_until_stopped()
        which blocks while running the macOS NSRunLoop.
        """
        if not self.connected:
            self.logger.error("Cannot run - mock RFCOMM not connected")
            return

        self.logger.info("Starting mock data streaming loop...")

        # Start streaming thread
        self.streaming_thread = threading.Thread(
            target=self._streaming_loop, daemon=True, name="MockRFCOMM"
        )
        self.streaming_thread.start()

        # Block until stopped (mimic NSRunLoop behavior)
        try:
            while not self.should_stop:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.logger.info("Mock streaming interrupted by user")
            self.should_stop = True

        # Wait for thread to finish
        if self.streaming_thread and self.streaming_thread.is_alive():
            self.streaming_thread.join(timeout=2.0)

        self.logger.info("Mock streaming loop stopped")

    def stop(self) -> None:
        """Signal to stop the mock streaming loop"""
        self.logger.info("Stop requested for mock RFCOMM streaming")
        self.should_stop = True

    def close(self) -> None:
        """Close mock RFCOMM connection and cleanup"""
        if self.connected:
            try:
                self.logger.info("Closing mock RFCOMM connection...")
                self.stop()
                self.connected = False
                self.should_stop = False  # Reset for potential reuse
                self.logger.info("Mock RFCOMM connection closed")
            except Exception as e:
                self.logger.error(f"Error closing mock RFCOMM: {e}")
        else:
            self.logger.debug("No mock RFCOMM connection to close")
            # Still reset state even if not connected
            self.should_stop = False
