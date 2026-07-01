"""Integration tests that run inside a Home Assistant test harness.

Requires pytest-homeassistant-custom-component (installed as the ``test`` extra in the
HA environment). Skipped automatically under the pure-library test run.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER  # noqa: E402
from homeassistant.const import CONF_ADDRESS  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.ebmx import protocol  # noqa: E402
from custom_components.ebmx.client import EbmxBleClient  # noqa: E402
from custom_components.ebmx.const import DOMAIN, NUS_RX_CHAR_UUID, NUS_SERVICE_UUID  # noqa: E402
from custom_components.ebmx.coordinator import EbmxCoordinator  # noqa: E402
from tests.fixtures_frames import GET_MCCONF_FRAME, GET_VALUES_FRAME_A  # noqa: E402

ADDRESS = "AA:BB:CC:DD:EE:FF"


def _fake_service_info(address: str = ADDRESS, name: str = "EBMX Bike"):
    """A minimal object exposing the attributes the flow/coordinator read."""
    return SimpleNamespace(
        address=address,
        name=name,
        service_uuids=[NUS_SERVICE_UUID],
        device=SimpleNamespace(address=address, name=name),
    )


class _FakeGattClient:
    """Replays captured frames into the notify callback; used via establish_connection."""

    def __init__(self) -> None:
        self._cb = None
        self.responses = {
            protocol.build_get_values_request(): GET_VALUES_FRAME_A,
            protocol.build_get_mcconf_request(): GET_MCCONF_FRAME,
        }

    async def start_notify(self, _c, cb) -> None:
        self._cb = cb

    async def stop_notify(self, _c) -> None:
        self._cb = None

    async def write_gatt_char(self, char, data, response: bool = False) -> None:
        assert char == NUS_RX_CHAR_UUID
        frame = self.responses.get(bytes(data))
        if frame and self._cb:
            asyncio.get_running_loop().call_soon(self._deliver, frame)

    def _deliver(self, frame: bytes) -> None:
        for i in range(0, len(frame), 20):
            self._cb(0, bytearray(frame[i : i + 20]))

    async def disconnect(self) -> None:
        self._cb = None


# --------------------------- config flow ---------------------------


async def test_bluetooth_discovery_creates_entry(hass, enable_custom_integrations) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_fake_service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == ADDRESS
    assert result["data"] == {CONF_ADDRESS: ADDRESS}


async def test_bluetooth_discovery_dedupes(hass, enable_custom_integrations) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_fake_service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_lists_discovered(hass, enable_custom_integrations) -> None:
    with patch(
        "custom_components.ebmx.config_flow.async_discovered_service_info",
        return_value=[_fake_service_info()],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == ADDRESS


async def test_user_flow_no_devices(hass, enable_custom_integrations) -> None:
    with patch(
        "custom_components.ebmx.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


# --------------------------- coordinator poll ---------------------------


async def test_coordinator_poll_decodes_real_frames(hass, enable_custom_integrations) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS})
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.bluetooth.update_coordinator.async_address_present",
        return_value=False,
    ):
        coordinator = EbmxCoordinator(hass, entry)

    fake_client = _FakeGattClient()
    with (
        patch(
            "custom_components.ebmx.coordinator.bluetooth.async_ble_device_from_address",
            return_value=SimpleNamespace(address=ADDRESS, name="EBMX Bike"),
        ),
        patch(
            "custom_components.ebmx.coordinator.establish_connection",
            AsyncMock(return_value=fake_client),
        ),
    ):
        data = await coordinator._async_poll(_fake_service_info())

    assert data.telemetry.battery_voltage == pytest.approx(79.9, abs=0.05)
    assert data.telemetry.controller_battery_percent == 86
    assert data.config is not None and data.config.inferred_cells == 20
    assert data.soc_estimate is not None and 75 <= data.soc_estimate <= 90
    # Cell count resolves through the coordinator property.
    assert coordinator.cells == 20


async def test_coordinator_cells_override(hass, enable_custom_integrations) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}, options={"cells": 24}
    )
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.bluetooth.update_coordinator.async_address_present",
        return_value=False,
    ):
        coordinator = EbmxCoordinator(hass, entry)
    assert coordinator.cells == 24  # override wins even before any config read
