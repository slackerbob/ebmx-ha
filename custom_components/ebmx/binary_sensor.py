"""Binary sensor platform: reports whether the bike is currently present/connectable."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbmxCoordinator
from .entity import EbmxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the presence binary sensor."""
    coordinator: EbmxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EbmxPresenceBinarySensor(coordinator)])


class EbmxPresenceBinarySensor(EbmxEntity, BinarySensorEntity):
    """On when the bike is advertising (i.e. powered on and in range of an adapter/proxy)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "present"

    def __init__(self, coordinator: EbmxCoordinator) -> None:
        super().__init__(coordinator, "present")

    @property
    def is_on(self) -> bool:
        return self.coordinator.available

    @property
    def available(self) -> bool:
        # The presence sensor itself is always available; its state carries the meaning.
        return True
