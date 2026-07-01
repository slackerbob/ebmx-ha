"""The EBMX X-Series Bluetooth integration.

Only the protocol/decoding modules (protocol, telemetry, client, const, models) are
import-safe without Home Assistant, which keeps the library unit-testable and runnable
standalone. This module therefore performs no top-level Home Assistant imports; the HA
wiring is imported lazily inside the setup functions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import DOMAIN  # noqa: F401  (re-exported for convenience)

PLATFORMS = ["sensor", "binary_sensor"]

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
	from homeassistant.config_entries import ConfigEntry
	from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
	"""Set up a bike from a config entry."""
	from .coordinator import EbmxCoordinator

	_LOGGER.debug(
		"Setting up EBMX entry: entry_id=%s title=%s unique_id=%s data=%s options=%s",
		entry.entry_id,
		entry.title,
		entry.unique_id,
		dict(entry.data),
		dict(entry.options),
	)

	coordinator = EbmxCoordinator(hass, entry)
	await coordinator.async_init()

	hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

	unsubscribe = coordinator.async_start()
	_LOGGER.debug("Coordinator started for entry_id=%s address=%s", entry.entry_id, coordinator.address)
	entry.async_on_unload(unsubscribe)

	await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
	_LOGGER.debug("Forwarded entry setups for entry_id=%s platforms=%s", entry.entry_id, PLATFORMS)

	entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
	return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
	"""Unload a config entry."""
	_LOGGER.debug("Unloading EBMX entry: entry_id=%s title=%s", entry.entry_id, entry.title)
	unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
	if unloaded:
		hass.data[DOMAIN].pop(entry.entry_id, None)
		_LOGGER.debug("Unloaded EBMX entry successfully: entry_id=%s", entry.entry_id)
	else:
		_LOGGER.debug("Failed to unload EBMX entry: entry_id=%s", entry.entry_id)
	return unloaded


async def _async_reload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
	"""Reload when options (e.g. cell-count override) change."""
	_LOGGER.debug("Reloading EBMX entry due to update: entry_id=%s", entry.entry_id)
	await hass.config_entries.async_reload(entry.entry_id)
