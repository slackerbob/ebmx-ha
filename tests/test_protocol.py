"""Unit tests for the VESC protocol layer (framing, CRC, reassembly)."""

from __future__ import annotations

import pytest

from custom_components.ebmx import protocol
from tests.fixtures_frames import GET_MCCONF_FRAME, GET_VALUES_FRAME_A


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def test_crc16_matches_captured_request() -> None:
    # The GET_VALUES request observed on the wire is exactly 02 01 04 40 84 03.
    assert protocol.build_get_values_request() == bytes.fromhex("020104408403")


def test_crc16_known_value() -> None:
    assert protocol.crc16_xmodem(bytes([protocol.COMM_GET_VALUES])) == 0x4084


def test_build_short_packet_roundtrips_through_packetizer() -> None:
    frame = protocol.build_short_packet(b"\x04\x01\x02\x03")
    out = list(protocol.VescPacketizer().feed(frame))
    assert out == [b"\x04\x01\x02\x03"]


def test_packetizer_reassembles_whole_frame() -> None:
    payloads = list(protocol.VescPacketizer().feed(GET_VALUES_FRAME_A))
    assert len(payloads) == 1
    assert payloads[0][0] == protocol.COMM_GET_VALUES
    assert len(payloads[0]) == 0x9D  # 157-byte payload


@pytest.mark.parametrize("mtu", [1, 3, 20, 23, 100, 244])
def test_packetizer_reassembles_across_fragmentation(mtu: int) -> None:
    # Simulate BLE notifications of various MTU-limited sizes.
    pkt = protocol.VescPacketizer()
    collected: list[bytes] = []
    for chunk in _chunks(GET_VALUES_FRAME_A, mtu):
        collected.extend(pkt.feed(chunk))
    assert len(collected) == 1
    assert collected[0][0] == protocol.COMM_GET_VALUES


def test_packetizer_handles_long_packet() -> None:
    payloads = list(protocol.VescPacketizer().feed(GET_MCCONF_FRAME))
    assert len(payloads) == 1
    assert payloads[0][0] == protocol.COMM_GET_MCCONF
    assert len(payloads[0]) == 0x1E5  # 485-byte payload


def test_packetizer_two_frames_back_to_back() -> None:
    stream = GET_VALUES_FRAME_A + GET_MCCONF_FRAME
    payloads = list(protocol.VescPacketizer().feed(stream))
    assert [p[0] for p in payloads] == [protocol.COMM_GET_VALUES, protocol.COMM_GET_MCCONF]


def test_packetizer_resyncs_past_leading_junk() -> None:
    stream = b"\xde\xad\xbe\xef" + GET_VALUES_FRAME_A
    payloads = list(protocol.VescPacketizer().feed(stream))
    assert len(payloads) == 1


def test_packetizer_drops_frame_with_bad_crc() -> None:
    corrupt = bytearray(GET_VALUES_FRAME_A)
    corrupt[10] ^= 0xFF  # flip a payload byte -> CRC will not match
    payloads = list(protocol.VescPacketizer().feed(bytes(corrupt)))
    assert payloads == []


def test_packetizer_waits_for_incomplete_frame() -> None:
    pkt = protocol.VescPacketizer()
    assert list(pkt.feed(GET_VALUES_FRAME_A[:50])) == []  # nothing yet
    payloads = list(pkt.feed(GET_VALUES_FRAME_A[50:]))
    assert len(payloads) == 1
