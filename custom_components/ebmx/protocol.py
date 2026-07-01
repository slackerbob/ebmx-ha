"""EBMX X-Series (X-9000) wire protocol: framing, CRC, and packet reassembly.

This module is deliberately dependency-free (standard library only) so it can be
unit-tested and reused with no Home Assistant or Bluetooth stack present.

The controller is VESC-derived and tunnels the VESC packet protocol over a Nordic
UART Service. A VESC packet is::

    short:  0x02 [len:1]    [payload...] [crc16:2 big-endian] 0x03
    long:   0x03 [len:2 BE] [payload...] [crc16:2 big-endian] 0x03

``len`` counts only the payload; the CRC is CRC-16/XMODEM over the payload; and the
payload's first byte is a VESC command id. Our requests are single-byte payloads
(always short packets); responses can be long (the config blob is ~485 bytes).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

_LOGGER = logging.getLogger(__name__)

START_SHORT = 0x02
START_LONG = 0x03
END_BYTE = 0x03

# VESC command ids we use.
COMM_GET_VALUES = 0x04
COMM_GET_MCCONF = 0x0E

# Guard against a corrupt length byte making us buffer without bound.
_MAX_BUFFER = 4096


def crc16_xmodem(data: bytes) -> int:
    """CRC-16/XMODEM: poly 0x1021, init 0x0000, no reflection, no final XOR."""
    crc = 0x0000
    for b in data:
        crc ^= b << 8
        crc &= 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_short_packet(payload: bytes) -> bytes:
    """Wrap a payload in a VESC short packet."""
    if len(payload) > 255:
        raise ValueError("payload too large for a short packet")
    crc = crc16_xmodem(payload)
    return bytes([START_SHORT, len(payload), *payload, crc >> 8, crc & 0xFF, END_BYTE])


def build_get_values_request() -> bytes:
    """Framed COMM_GET_VALUES request (constant: 02 01 04 40 84 03)."""
    return build_short_packet(bytes([COMM_GET_VALUES]))


def build_get_mcconf_request() -> bytes:
    """Framed COMM_GET_MCCONF request."""
    return build_short_packet(bytes([COMM_GET_MCCONF]))


class VescPacketizer:
    """Reassembles complete VESC packets from an arbitrarily chunked byte stream.

    A GET_VALUES response is ~162 bytes and a GET_MCCONF response ~490 bytes; unless a
    large ATT MTU is negotiated, the controller (or a Bluetooth proxy) splits these
    across several notifications. ``feed`` buffers everything and yields each complete,
    CRC-verified payload (each starting with its command-id byte). It resynchronises
    past junk or a bad CRC rather than wedging.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, incoming: bytes) -> Iterator[bytes]:
        """Feed received bytes; yield every complete payload now extractable."""
        self._buffer.extend(incoming)
        if len(self._buffer) > _MAX_BUFFER:
            _LOGGER.warning("VESC buffer exceeded %d bytes; clearing to resync", _MAX_BUFFER)
            self._buffer.clear()
            return
        while True:
            payload = self._extract_one()
            if payload is None:
                return
            yield payload

    def _extract_one(self) -> bytes | None:
        buf = self._buffer
        while True:
            # Seek a valid start byte.
            while buf and buf[0] not in (START_SHORT, START_LONG):
                del buf[0]
            if not buf:
                return None

            length_field = 1 if buf[0] == START_SHORT else 2
            header = 1 + length_field
            if len(buf) < header:
                return None

            if length_field == 1:
                payload_len = buf[1]
            else:
                payload_len = (buf[1] << 8) | buf[2]

            total = header + payload_len + 2 + 1  # + crc(2) + end(1)
            if len(buf) < total:
                return None

            if buf[total - 1] != END_BYTE:
                # Misaligned; drop one byte and resync.
                del buf[0]
                continue

            payload = bytes(buf[header : header + payload_len])
            recv_crc = (buf[header + payload_len] << 8) | buf[header + payload_len + 1]
            del buf[:total]  # consume regardless, to keep moving

            if recv_crc != crc16_xmodem(payload):
                _LOGGER.warning("VESC CRC mismatch; dropping frame")
                continue

            return payload
