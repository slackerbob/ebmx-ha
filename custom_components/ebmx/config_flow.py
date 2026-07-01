"""Config flow for the EBMX X-Series integration.

Each bike becomes its own config entry (and therefore its own HA device), keyed by its
Bluetooth address. Bikes can be added automatically when Home Assistant discovers one
advertising the Nordic UART Service, or manually from the list of currently-visible
devices.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
	BluetoothServiceInfoBleak,
	async_discovered_service_info,
)
from homeassistant.config_entries import (
	ConfigEntry,
	ConfigFlow,
	ConfigFlowResult,
	OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import CONF_CELLS, DOMAIN, NUS_SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


def _title(info: BluetoothServiceInfoBleak) -> str:
	return info.name or f"EBMX {info.address}"


def _looks_like_ebmx(info: BluetoothServiceInfoBleak) -> bool:
	"""Best-effort fallback matcher for bikes HA can see but can't UUID-match."""
	name = (info.name or "").lower()
	return "ebmx" in name


class EbmxConfigFlow(ConfigFlow, domain=DOMAIN):
	"""Handle a config flow for EBMX bikes."""

	VERSION = 1

	def __init__(self) -> None:
		self._discovery: BluetoothServiceInfoBleak | None = None
		self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

	async def async_step_bluetooth(
		self, discovery_info: BluetoothServiceInfoBleak
	) -> ConfigFlowResult:
		"""Handle a bike discovered over Bluetooth."""
		_LOGGER.debug(
			"Bluetooth discovery: address=%s name=%s uuids=%s",
			discovery_info.address,
			discovery_info.name,
			discovery_info.service_uuids,
		)
		await self.async_set_unique_id(discovery_info.address)
		self._abort_if_unique_id_configured()
		self._discovery = discovery_info
		self.context["title_placeholders"] = {"name": _title(discovery_info)}
		return await self.async_step_bluetooth_confirm()

	async def async_step_bluetooth_confirm(
		self, user_input: dict[str, Any] | None = None
	) -> ConfigFlowResult:
		"""Confirm adding a discovered bike."""
		assert self._discovery is not None
		if user_input is not None:
			_LOGGER.debug("Bluetooth confirm accepted for address=%s", self._discovery.address)
			return self.async_create_entry(
				title=_title(self._discovery),
				data={CONF_ADDRESS: self._discovery.address},
			)
		self._set_confirm_only()
		return self.async_show_form(
			step_id="bluetooth_confirm",
			description_placeholders={"name": _title(self._discovery)},
		)

	async def async_step_user(
		self, user_input: dict[str, Any] | None = None
	) -> ConfigFlowResult:
		"""Add a bike by picking from currently-visible devices."""
		if user_input is not None:
			if user_input.get("use_manual"):
				_LOGGER.debug("User flow switching to manual entry")
				return await self.async_step_manual()

			address = user_input[CONF_ADDRESS]
			_LOGGER.debug("User selected discovered device address=%s", address)
			await self.async_set_unique_id(address, raise_on_progress=False)
			self._abort_if_unique_id_configured()
			info = self._discovered[address]
			return self.async_create_entry(
				title=_title(info), data={CONF_ADDRESS: address}
			)

		current = self._async_current_ids()
		for info in async_discovered_service_info(self.hass):
			if info.address in current or info.address in self._discovered:
				continue
			service_uuids = {uuid.lower() for uuid in info.service_uuids}
			matched = NUS_SERVICE_UUID.lower() in service_uuids or _looks_like_ebmx(info)
			_LOGGER.debug(
				"Inspecting discovered device address=%s name=%s uuids=%s matched=%s",
				info.address,
				info.name,
				info.service_uuids,
				matched,
			)
			if matched:
				self._discovered[info.address] = info

		if not self._discovered:
			_LOGGER.debug("No matching discovered devices; falling back to manual entry")
			return await self.async_step_manual()

		_LOGGER.debug("Found %d candidate devices for manual add", len(self._discovered))
		return self.async_show_form(
			step_id="user",
			data_schema=vol.Schema(
				{
					vol.Required(CONF_ADDRESS): vol.In(
						{addr: _title(info) for addr, info in self._discovered.items()}
					),
					vol.Optional("use_manual", default=False): bool,
				}
			),
		)

	async def async_step_manual(
		self, user_input: dict[str, Any] | None = None
	) -> ConfigFlowResult:
		"""Add a bike by manually entering its Bluetooth address."""
		errors: dict[str, str] = {}

		if user_input is not None:
			address = user_input[CONF_ADDRESS].upper()
			_LOGGER.debug("Manual address entry: address=%s", address)
			await self.async_set_unique_id(address, raise_on_progress=False)
			self._abort_if_unique_id_configured()
			return self.async_create_entry(
				title=f"EBMX {address}",
				data={CONF_ADDRESS: address},
			)

		return self.async_show_form(
			step_id="manual",
			data_schema=vol.Schema(
				{
					vol.Required(CONF_ADDRESS): str,
				}
			),
			errors=errors,
		)

	@staticmethod
	@callback
	def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
		return EbmxOptionsFlow()


class EbmxOptionsFlow(OptionsFlow):
	"""Options: override the series cell count used for the SOC estimate."""

	async def async_step_init(
		self, user_input: dict[str, Any] | None = None
	) -> ConfigFlowResult:
		if user_input is not None:
			cells = user_input.get(CONF_CELLS)
			data = {CONF_CELLS: int(cells)} if cells else {}
			_LOGGER.debug("Options updated for entry_id=%s cells=%s", self.config_entry.entry_id, cells)
			return self.async_create_entry(title="", data=data)

		current = self.config_entry.options.get(CONF_CELLS, "")
		return self.async_show_form(
			step_id="init",
			data_schema=vol.Schema(
				{
					vol.Optional(
						CONF_CELLS,
						description={"suggested_value": current},
					): cv.positive_int,
				}
			),
		)
