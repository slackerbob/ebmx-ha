"""The EBMX X-Series Bluetooth integration.

Only the protocol/decoding modules (protocol, telemetry, client, const, models) are
import-safe without Home Assistant, which keeps the library unit-testable and runnable
standalone. This module therefore performs no top-level Home Assistant imports; the HA
wiring is imported lazily inside the setup functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN  # noqa: F401  (re-exported for convenience)

PLATFORMS = ["sensor", "binary_sensor"]

if TYPE_CHECKING:
	from homeassistant.config_entries import ConfigEntry
	from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
	"""Set up a bike from a config entry."""
	from .coordinator import EbmxCoordinator

	coordinator = EbmxCoordinator(hass, entry)
	await coordinator.async_init()

	hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
	entry.async_on_unload(coordinator.async_start())

	await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
	entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
	return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
	"""Unload a config entry."""
	unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
	if unloaded:
		hass.data[DOMAIN].pop(entry.entry_id, None)
	return unloaded


async def _async_reload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
	"""Reload when options (e.g. cell-count override) change."""
	await hass.config_entries.async_reload(entry.entry_id)
