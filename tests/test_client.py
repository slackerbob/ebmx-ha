"""Integration tests for :class:`EbmxBleClient` against a fake GATT client.

These exercise the full connect -> subscribe -> request -> reassemble -> decode pipeline
with no real Bluetooth and no Home Assistant: a fake client replays captured frames
(optionally fragmented) into the notification callback, exactly as a real controller or
Bluetooth proxy would.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.ebmx import protocol
from custom_components.ebmx.client import EbmxBleClient
from custom_components.ebmx.const import NUS_RX_CHAR_UUID
from tests.fixtures_frames import GET_MCCONF_FRAME, GET_VALUES_FRAME_A


class FakeGattClient:
    """Minimal stand-in for bleak.BleakClient.

    When a known request is written, it delivers the corresponding response frame to the
    notification callback, split into ``mtu``-sized chunks to mimic BLE fragmentation.
    """

    def __init__(self, mtu: int = 20, delay: float = 0.0) -> None:
        self.mtu = mtu
        self.delay = delay
        self._callback = None
        self.written: list[bytes] = []
        self.responses = {
            protocol.build_get_values_request(): GET_VALUES_FRAME_A,
            protocol.build_get_mcconf_request(): GET_MCCONF_FRAME,
        }

    async def start_notify(self, _char, callback) -> None:
        self._callback = callback

    async def stop_notify(self, _char) -> None:
        self._callback = None

    async def write_gatt_char(self, char, data, response: bool = False) -> None:
        assert char == NUS_RX_CHAR_UUID
        self.written.append(bytes(data))
        frame = self.responses.get(bytes(data))
        if frame is None or self._callback is None:
            return
        # Deliver asynchronously, fragmented, like a proxy would.
        asyncio.get_running_loop().create_task(self._deliver(frame))

    async def _deliver(self, frame: bytes) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        for i in range(0, len(frame), self.mtu):
            self._callback(0, bytearray(frame[i : i + self.mtu]))


async def test_read_values_over_fake_client() -> None:
    ebmx = EbmxBleClient(FakeGattClient(mtu=20))
    await ebmx.start()
    telemetry = await ebmx.read_values(timeout=1.0)
    assert telemetry.battery_voltage == pytest.approx(79.9, abs=0.05)
    assert telemetry.controller_battery_percent == 86
    await ebmx.stop()


@pytest.mark.parametrize("mtu", [1, 3, 20, 244])
async def test_read_values_survives_fragmentation(mtu: int) -> None:
    ebmx = EbmxBleClient(FakeGattClient(mtu=mtu))
    await ebmx.start()
    telemetry = await ebmx.read_values(timeout=1.0)
    assert telemetry.controller_battery_percent == 86
    await ebmx.stop()


async def test_read_config_over_fake_client() -> None:
    ebmx = EbmxBleClient(FakeGattClient(mtu=20))
    await ebmx.start()
    cfg = await ebmx.read_config(timeout=1.0)
    assert cfg is not None
    assert cfg.inferred_cells == 20
    assert cfg.signature == 0x968A9B08
    await ebmx.stop()


async def test_config_then_values_interleaved() -> None:
    client = FakeGattClient(mtu=20)
    ebmx = EbmxBleClient(client)
    await ebmx.start()
    cfg = await ebmx.read_config(timeout=1.0)
    telemetry = await ebmx.read_values(timeout=1.0)
    assert cfg is not None and cfg.inferred_cells == 20
    assert telemetry.controller_battery_percent == 86
    # One write per request.
    assert len(client.written) == 2
    await ebmx.stop()


async def test_read_values_times_out_when_no_response() -> None:
    client = FakeGattClient()
    client.responses = {}  # never answers
    ebmx = EbmxBleClient(client)
    await ebmx.start()
    with pytest.raises(asyncio.TimeoutError):
        await ebmx.read_values(timeout=0.2)
    await ebmx.stop()


async def test_read_config_returns_none_on_timeout() -> None:
    client = FakeGattClient()
    client.responses = {}
    ebmx = EbmxBleClient(client)
    await ebmx.start()
    assert await ebmx.read_config(timeout=0.2) is None
    await ebmx.stop()


async def test_request_before_start_raises() -> None:
    ebmx = EbmxBleClient(FakeGattClient())
    with pytest.raises(RuntimeError):
        await ebmx.read_values(timeout=0.2)
