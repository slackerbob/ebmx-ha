"""Update platform: surfaces EBMX controller firmware availability.

This is deliberately *report-only*. It tells you when a newer firmware build than the one
on the controller has been published, and links to the release, but it does not flash
anything — over-the-air VESC bootloader flashing is risky and best done with the official
RideControl app. So no INSTALL feature is advertised; Home Assistant shows the version
comparison and an "update available" state without an install button.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_VARIANT, DEFAULT_VARIANT, DOMAIN
from .coordinator import EbmxCoordinator
from .entity import EbmxEntity
from .firmware import (
	FIRMWARE_MANIFEST_URL,
	FIRMWARE_REPO_URL,
	FirmwareRelease,
	parse_manifest,
)

_LOGGER = logging.getLogger(__name__)

# The manifest changes rarely; check once a day (plus once at startup).
_REFRESH_INTERVAL = timedelta(hours=24)


async def async_setup_entry(
	hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
	"""Set up the firmware update entity for a bike."""
	coordinator: EbmxCoordinator = hass.data[DOMAIN][entry.entry_id]
	async_add_entities([EbmxFirmwareUpdate(coordinator)])


class EbmxFirmwareUpdate(EbmxEntity, UpdateEntity):
	"""Compares the controller's installed firmware date with the published latest."""

	_attr_device_class = UpdateDeviceClass.FIRMWARE
	_attr_translation_key = "firmware"
	_attr_supported_features = 0  # report-only: no install button

	def __init__(self, coordinator: EbmxCoordinator) -> None:
		super().__init__(coordinator, "firmware")
		self._manifest_raw: str | None = None

	@property
	def _variant(self) -> str:
		return self.coordinator.entry.options.get(CONF_VARIANT, DEFAULT_VARIANT)

	@property
	def _release(self) -> FirmwareRelease | None:
		if not self._manifest_raw:
			return None
		hardware = self.coordinator.fw_info.hardware if self.coordinator.fw_info else None
		return parse_manifest(self._manifest_raw, hardware=hardware, variant=self._variant)

	@property
	def installed_version(self) -> str | None:
		info = self.coordinator.fw_info
		return info.version if info else None

	@property
	def latest_version(self) -> str | None:
		release = self._release
		# When we can't reach the manifest, don't claim an update: fall back to installed.
		return release.version if release else self.installed_version

	@property
	def title(self) -> str:
		hardware = self.coordinator.fw_info.hardware if self.coordinator.fw_info else None
		return f"{hardware or 'EBMX'} firmware"

	@property
	def release_url(self) -> str:
		release = self._release
		return release.release_url if release else FIRMWARE_REPO_URL

	@property
	def release_summary(self) -> str | None:
		release = self._release
		if release is None:
			return None
		return (
			f"Latest published build for {release.model} ({release.variant}) is "
			f"{release.version}. Flash it with the official RideControl app — this "
			f"integration reports availability only."
		)

	@property
	def available(self) -> bool:
		# Report-only entity; useful even if the bike is asleep or the network is down.
		return True

	async def async_added_to_hass(self) -> None:
		await super().async_added_to_hass()
		# Initial fetch now, then daily.
		await self._async_refresh_manifest()
		self.async_on_remove(
			async_track_time_interval(self.hass, self._async_refresh_manifest, _REFRESH_INTERVAL)
		)

	async def _async_refresh_manifest(self, _now=None) -> None:
		"""Fetch the firmware manifest and update state."""
		session = async_get_clientsession(self.hass)
		try:
			async with session.get(
				FIRMWARE_MANIFEST_URL, timeout=aiohttp.ClientTimeout(total=20)
			) as resp:
				resp.raise_for_status()
				self._manifest_raw = await resp.text()
				_LOGGER.debug("%s: fetched firmware manifest", self.coordinator.address)
		except (aiohttp.ClientError, TimeoutError) as err:
			_LOGGER.debug("%s: firmware manifest fetch failed: %s", self.coordinator.address, err)
		self.async_write_ha_state()

	@callback
	def _handle_coordinator_update(self) -> None:
		# Pick up the installed version once the coordinator has read it from the bike.
		super()._handle_coordinator_update()
