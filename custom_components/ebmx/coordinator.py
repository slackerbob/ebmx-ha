"""Coordinator that polls one EBMX bike over Home Assistant's Bluetooth stack.

Uses ``ActiveBluetoothDataUpdateCoordinator``: Home Assistant delivers the bike's BLE
advertisements (relayed through any Bluetooth proxy transparently), and on each one we
decide whether a poll is due. Polls are additionally debounced to at most once every
~10 s by the coordinator itself. When the bike is off/out of range there are no
advertisements, so we simply don't poll — exactly the behaviour wanted for a vehicle
that's only powered on for short windows.

The actual connect/read is done with ``bleak_retry_connector.establish_connection``,
which automatically routes through the best available adapter or proxy.
"""

from __future__ import annotations

import logging

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.active_update_coordinator import (
	ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.util import dt as dt_util

from .client import EbmxBleClient
from .const import CONF_CELLS, DOMAIN, POLL_INTERVAL_SECONDS
from .models import EbmxData
from .telemetry import McConfig, estimate_soc_percent

_LOGGER = logging.getLogger(__name__)


class EbmxCoordinator(ActiveBluetoothDataUpdateCoordinator[EbmxData]):
	"""Polls a single bike and shares the latest :class:`EbmxData`."""

	def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
		self.entry = entry
		self.address: str = entry.unique_id or entry.data["address"]
		self.title: str = entry.title
		self._cells_override: int | None = entry.options.get(CONF_CELLS)
		self._config: McConfig | None = None
		self.last_success_time = None

		super().__init__(
			hass=hass,
			logger=_LOGGER,
			address=self.address,
			mode=bluetooth.BluetoothScanningMode.PASSIVE,
			needs_poll_method=self._needs_poll,
			poll_method=self._async_poll,
			connectable=True,
		)

	async def async_init(self) -> None:
		"""One-off setup hook (kept for symmetry / future use)."""

	@property
	def device_info(self) -> DeviceInfo:
		"""Device entry for this bike (one HA device per bike)."""
		return DeviceInfo(
			identifiers={(DOMAIN, self.address)},
			connections={(CONNECTION_BLUETOOTH, self.address)},
			name=self.title,
			manufacturer="EBMX",
			model="X-Series (X-9000)",
		)

	@property
	def cells(self) -> int:
		"""Series cell count for the SOC estimate (override or inferred)."""
		if self._cells_override:
			return self._cells_override
		return self._config.inferred_cells if self._config else 0

	@callback
	def _needs_poll(
		self, service_info: bluetooth.BluetoothServiceInfoBleak, seconds_since_last_poll: float | None
	) -> bool:
		return (
			self.hass.state is CoreState.running
			and (seconds_since_last_poll is None or seconds_since_last_poll >= POLL_INTERVAL_SECONDS)
			and bool(
			bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
		)
		)

	async def _async_poll(self, service_info: bluetooth.BluetoothServiceInfoBleak) -> EbmxData:
		"""Connect (via proxy if needed), read config once, poll telemetry."""
		ble_device = (
			bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
			or service_info.device
		)

		client = await establish_connection(
			BleakClientWithServiceCache, ble_device, self.address
		)
		try:
			ebmx = EbmxBleClient(client)
			await ebmx.start()
			if self._config is None:
				self._config = await ebmx.read_config()
				if self._config and self._config.cut_plausible:
					_LOGGER.debug(
						"%s: config sig=0x%08X cut=%.1f/%.1fV cells=%d",
						self.address,
						self._config.signature,
						self._config.cut_start_volts,
						self._config.cut_end_volts,
						self._config.inferred_cells,
					)
			telemetry = await ebmx.read_values()
			await ebmx.stop()
		finally:
			await client.disconnect()

		soc = estimate_soc_percent(telemetry.battery_voltage, self.cells, self._config)
		self.last_success_time = dt_util.utcnow()
		return EbmxData(telemetry=telemetry, config=self._config, soc_estimate=soc)
