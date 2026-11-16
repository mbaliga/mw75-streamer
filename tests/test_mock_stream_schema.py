"""Short --mock style run: checksum validity, counter continuity, frozen WS schema.

No wall-clock rate assertion: the mock targets ~500 Hz but CI runners vary.
"""

import json
import threading
from typing import Any, List

from mw75_streamer.data.packet_processor import EEGPacket, PacketProcessor
from mw75_streamer.data.streamers import WebSocketStreamer
from mw75_streamer.device.mock_rfcomm_manager import MockRFCOMMManager

# The WebSocket JSON output schema is frozen (downstream consumers depend on it).
# Changing this list is a breaking change and needs an explicit decision.
FROZEN_TOP_LEVEL_KEYS = [
    "timestamp",
    "event_id",
    "counter",
    "ref",
    "drl",
    "channels",
    "feature_status",
    "type",
]
FROZEN_CHANNEL_KEYS = [f"ch{i}" for i in range(1, 13)]

N_PACKETS = 300  # > 256 so the counter wrap is exercised


def _run_mock(n: int) -> List[bytes]:
    received: List[bytes] = []
    done = threading.Event()
    mgr: MockRFCOMMManager

    def on_data(data: bytes) -> None:
        if len(received) < n:
            received.append(data)
        if len(received) >= n:
            mgr.stop()
            done.set()

    mgr = MockRFCOMMManager("MW75-TEST", on_data)
    assert mgr.connect() is True
    runner = threading.Thread(target=mgr.run_until_stopped, daemon=True)
    runner.start()
    assert done.wait(timeout=30), "mock produced too few packets"
    runner.join(timeout=5)
    mgr.close()
    return received


def _parse(raw: List[bytes]) -> List[EEGPacket]:
    proc = PacketProcessor()
    out: List[EEGPacket] = []
    for chunk in raw:
        proc.process_data_buffer(chunk, out.append)
    assert proc.stats.invalid_packets == 0
    return out


def test_mock_run_checksums_valid_and_counters_continuous() -> None:
    parsed = _parse(_run_mock(N_PACKETS))
    assert len(parsed) == N_PACKETS
    assert all(p.checksum_valid for p in parsed)
    counters = [p.counter for p in parsed]
    assert counters == [i % 256 for i in range(N_PACKETS)]


class _FakeClient:
    def __init__(self) -> None:
        self.sent: List[Any] = []

    def send(self, payload: str) -> None:
        self.sent.append(payload)


def test_websocket_json_schema_is_frozen() -> None:
    streamer = WebSocketStreamer(None)
    fake = _FakeClient()
    streamer.client = fake
    streamer.connected = True
    for pkt in _parse(_run_mock(5)):
        assert streamer.send_eeg_data(pkt) is True

    assert len(fake.sent) == 5
    for payload in fake.sent:
        doc = json.loads(payload)
        assert list(doc.keys()) == FROZEN_TOP_LEVEL_KEYS
        assert list(doc["channels"].keys()) == FROZEN_CHANNEL_KEYS
        assert doc["type"] == "eeg_data"
        assert all(isinstance(v, float) for v in doc["channels"].values())
