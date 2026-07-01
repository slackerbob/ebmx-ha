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

		_LOGGER.debug(
			"Creating coordinator: entry_id=%s address=%s title=%s cells_override=%s",
			entry.entry_id,
			self.address,
			self.title,
			self._cells_override,
		)

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
		_LOGGER.debug("Coordinator async_init: address=%s", self.address)

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
		ble_device = bluetooth.async_ble_device_from_address(
			self.hass, self.address, connectable=True
		)
		should_poll = (
			self.hass.state is CoreState.running
			and (seconds_since_last_poll is None or seconds_since_last_poll >= POLL_INTERVAL_SECONDS)
			and bool(ble_device)
		)
		_LOGGER.debug(
			"%s: _needs_poll=%s seconds_since_last_poll=%s hass_state=%s seen_name=%s seen_address=%s connectable_device=%s service_uuids=%s",
			self.address,
			should_poll,
			seconds_since_last_poll,
			self.hass.state,
			getattr(service_info, "name", None),
			getattr(service_info, "address", None),
			bool(ble_device),
			getattr(service_info, "service_uuids", None),
		)
		return should_poll

	async def _async_poll(self) -> EbmxData:
		"""Connect (via proxy if needed), read config once, poll telemetry."""
		_LOGGER.debug("%s: starting poll", self.address)

		ble_device = bluetooth.async_ble_device_from_address(
			self.hass, self.address, connectable=True
		)
		if ble_device is None:
			_LOGGER.debug("%s: no connectable BLE device found at poll time", self.address)
			raise RuntimeError(f"{self.address}: BLE device not currently available")

		_LOGGER.debug(
			"%s: establishing connection to ble_device=%s",
			self.address,
			ble_device,
		)

		client = await establish_connection(
			BleakClientWithServiceCache, ble_device, self.address
		)
		_LOGGER.debug("%s: BLE connection established", self.address)

		try:
			ebmx = EbmxBleClient(client)
			await ebmx.start()
			_LOGGER.debug("%s: notification subscription started", self.address)

			if self._config is None:
				_LOGGER.debug("%s: reading config", self.address)
				self._config = await ebmx.read_config()
				if self._config is None:
					_LOGGER.debug("%s: no config returned", self.address)
				elif self._config.cut_plausible:
					_LOGGER.debug(
						"%s: config sig=0x%08X cut=%.1f/%.1fV cells=%d",
						self.address,
						self._config.signature,
						self._config.cut_start_volts,
						self._config.cut_end_volts,
						self._config.inferred_cells,
					)
				else:
					_LOGGER.debug(
						"%s: config returned but cutoffs not plausible sig=0x%08X cut=%.1f/%.1fV",
						self.address,
						self._config.signature,
						self._config.cut_start_volts,
						self._config.cut_end_volts,
					)

			_LOGGER.debug("%s: reading telemetry", self.address)
			telemetry = await ebmx.read_values()
			_LOGGER.debug(
				"%s: telemetry read voltage=%s controller_soc=%s rpm=%s speed=%s fault=%s",
				self.address,
				telemetry.battery_voltage,
				telemetry.controller_battery_percent,
				telemetry.rpm,
				telemetry.speed_kph,
				telemetry.fault,
			)

			await ebmx.stop()
			_LOGGER.debug("%s: notification subscription stopped", self.address)
		except Exception:
			_LOGGER.exception("%s: poll failed", self.address)
			raise
		finally:
			await client.disconnect()
			_LOGGER.debug("%s: BLE client disconnected", self.address)

		soc = estimate_soc_percent(telemetry.battery_voltage, self.cells, self._config)
		self.last_success_time = dt_util.utcnow()
		_LOGGER.debug(
			"%s: poll complete soc_estimate=%s cells=%s last_success_time=%s",
			self.address,
			soc,
			self.cells,
			self.last_success_time,
		)
		return EbmxData(telemetry=telemetry, config=self._config, soc_estimate=soc)
