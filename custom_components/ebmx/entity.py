"""Shared entity base for EBMX sensors."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .coordinator import EbmxCoordinator


class EbmxEntity(PassiveBluetoothCoordinatorEntity[EbmxCoordinator]):
    """Base entity: names/grouping and cached-value availability.

    The coordinator keeps its last successful :class:`EbmxData` in ``self.data`` even
    after the bike goes away, so reading from it means the dashboard keeps showing the
    last-known values (the requested caching behaviour). A separate connectivity
    binary_sensor reports whether the bike is actually present right now.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: EbmxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info
