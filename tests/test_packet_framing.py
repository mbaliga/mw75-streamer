"""Packet framing and checksum tests (no hardware, no OS-specific code)."""

import struct

from mw75_streamer.config import EEG_EVENT_ID, NUM_EEG_CHANNELS, PACKET_SIZE, SYNC_BYTE
from mw75_streamer.data.packet_processor import EEGPacket, PacketProcessor
from mw75_streamer.device.mock_rfcomm_manager import build_eeg_packet


def test_built_packet_header_and_size() -> None:
    packet = build_eeg_packet(7)
    assert len(packet) == PACKET_SIZE == 63
    assert packet[0] == SYNC_BYTE
    assert packet[1] == EEG_EVENT_ID
    assert packet[2] == 0x3C
    assert packet[3] == 7


def test_built_packet_checksum_is_sum_of_first_61_bytes_le() -> None:
    packet = build_eeg_packet(1)
    expected = sum(packet[:61]) & 0xFFFF
    assert struct.unpack("<H", packet[61:63])[0] == expected


def test_counter_wraps_at_256() -> None:
    assert build_eeg_packet(256)[3] == 0
    assert build_eeg_packet(257)[3] == 1


def test_validate_checksum_accepts_good_and_rejects_corrupt() -> None:
    proc = PacketProcessor()
    packet = build_eeg_packet(3)
    assert proc.validate_checksum(packet)[0] is True
    corrupt = bytearray(packet)
    corrupt[20] ^= 0xFF
    assert proc.validate_checksum(bytes(corrupt))[0] is False


def test_validate_checksum_rejects_short_packet() -> None:
    assert PacketProcessor().validate_checksum(b"\xaa" * 10) == (False, 0, 0)


def test_parse_eeg_packet_fields() -> None:
    proc = PacketProcessor()
    parsed = proc.parse_eeg_packet(build_eeg_packet(9))
    assert isinstance(parsed, EEGPacket)
    assert parsed.counter == 9
    assert parsed.event_id == EEG_EVENT_ID
    assert len(parsed.channels) == NUM_EEG_CHANNELS
    assert parsed.checksum_valid is True
    assert proc.stats.valid_packets == 1


def test_parse_rejects_bad_sync_and_bad_checksum() -> None:
    proc = PacketProcessor()
    bad_sync = bytearray(build_eeg_packet(0))
    bad_sync[0] = 0x00
    assert proc.parse_eeg_packet(bytes(bad_sync)) is None
    bad_sum = bytearray(build_eeg_packet(0))
    bad_sum[62] ^= 0x01
    assert proc.parse_eeg_packet(bytes(bad_sum)) is None
    assert proc.stats.invalid_packets == 1


def test_framing_across_arbitrary_chunk_sizes() -> None:
    """RFCOMM delivers arbitrary chunks (e.g. 64 B); packets must reassemble."""
    stream = b"".join(build_eeg_packet(i) for i in range(10))
    for chunk in (1, 7, 63, 64, 100):
        proc = PacketProcessor()
        counters = []
        for start in range(0, len(stream), chunk):
            proc.process_data_buffer(stream[start : start + chunk], lambda p: counters.append(p.counter))
        assert counters == list(range(10)), f"chunk={chunk}"


def test_framing_resyncs_after_garbage_prefix() -> None:
    proc = PacketProcessor()
    seen = []
    data = b"\x01\x02\x03" + build_eeg_packet(5) + build_eeg_packet(6)
    proc.process_data_buffer(data, lambda p: seen.append(p.counter))
    assert seen == [5, 6]


def test_non_eeg_event_goes_to_other_callback() -> None:
    packet = bytearray(build_eeg_packet(0))
    packet[1] = 0x01
    packet[61:63] = struct.pack("<H", sum(packet[:61]) & 0xFFFF)
    eeg, other = [], []
    PacketProcessor().process_data_buffer(bytes(packet), eeg.append, other.append)
    assert eeg == []
    assert len(other) == 1
