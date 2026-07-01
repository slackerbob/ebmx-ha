"""Sensor platform for the EBMX X-Series integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
	RestoreSensor,
	SensorDeviceClass,
	SensorEntityDescription,
	SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
	PERCENTAGE,
	EntityCategory,
	UnitOfElectricCurrent,
	UnitOfElectricPotential,
	UnitOfLength,
	UnitOfPower,
	UnitOfSpeed,
	UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbmxCoordinator
from .entity import EbmxEntity
from .models import EbmxData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EbmxSensorDescription(SensorEntityDescription):
	"""Sensor description with a function to pull the value out of EbmxData."""

	value_fn: Callable[[EbmxData], float | int | None]


SENSORS: tuple[EbmxSensorDescription, ...] = (
	EbmxSensorDescription(
		key="battery_voltage",
		translation_key="battery_voltage",
		device_class=SensorDeviceClass.VOLTAGE,
		native_unit_of_measurement=UnitOfElectricPotential.VOLT,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=1,
		value_fn=lambda d: d.telemetry.battery_voltage,
	),
	EbmxSensorDescription(
		key="battery_soc_controller",
		translation_key="battery_soc_controller",
		device_class=SensorDeviceClass.BATTERY,
		native_unit_of_measurement=PERCENTAGE,
		state_class=SensorStateClass.MEASUREMENT,
		value_fn=lambda d: d.telemetry.controller_battery_percent,
	),
	EbmxSensorDescription(
		key="battery_soc_estimate",
		translation_key="battery_soc_estimate",
		native_unit_of_measurement=PERCENTAGE,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=0,
		value_fn=lambda d: d.soc_estimate,
	),
	EbmxSensorDescription(
		key="input_current",
		translation_key="input_current",
		device_class=SensorDeviceClass.CURRENT,
		native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=1,
		value_fn=lambda d: d.telemetry.input_current,
	),
	EbmxSensorDescription(
		key="motor_current",
		translation_key="motor_current",
		device_class=SensorDeviceClass.CURRENT,
		native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=1,
		value_fn=lambda d: d.telemetry.motor_current,
	),
	EbmxSensorDescription(
		key="power",
		translation_key="power",
		device_class=SensorDeviceClass.POWER,
		native_unit_of_measurement=UnitOfPower.WATT,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=0,
		value_fn=lambda d: d.telemetry.power_watts,
	),
	EbmxSensorDescription(
		key="speed",
		translation_key="speed",
		device_class=SensorDeviceClass.SPEED,
		native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=1,
		value_fn=lambda d: d.telemetry.speed_kph,
	),
	EbmxSensorDescription(
		key="rpm",
		translation_key="rpm",
		native_unit_of_measurement="rpm",
		state_class=SensorStateClass.MEASUREMENT,
		value_fn=lambda d: d.telemetry.rpm,
	),
	EbmxSensorDescription(
		key="duty_cycle",
		translation_key="duty_cycle",
		native_unit_of_measurement=PERCENTAGE,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=0,
		# duty is 0..1; present as a percentage.
		value_fn=lambda d: None if d.telemetry.duty_cycle is None else d.telemetry.duty_cycle * 100.0,
	),
	EbmxSensorDescription(
		key="temp_fet",
		translation_key="temp_fet",
		device_class=SensorDeviceClass.TEMPERATURE,
		native_unit_of_measurement=UnitOfTemperature.CELSIUS,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=1,
		value_fn=lambda d: d.telemetry.temp_fet,
	),
	EbmxSensorDescription(
		key="temp_motor",
		translation_key="temp_motor",
		device_class=SensorDeviceClass.TEMPERATURE,
		native_unit_of_measurement=UnitOfTemperature.CELSIUS,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=1,
		entity_registry_enabled_default=False,  # often no motor NTC fitted
		value_fn=lambda d: d.telemetry.temp_motor,
	),
	EbmxSensorDescription(
		key="throttle",
		translation_key="throttle",
		native_unit_of_measurement=PERCENTAGE,
		state_class=SensorStateClass.MEASUREMENT,
		suggested_display_precision=0,
		value_fn=lambda d: d.telemetry.throttle_percent,
	),
	EbmxSensorDescription(
		key="odometer",
		translation_key="odometer",
		device_class=SensorDeviceClass.DISTANCE,
		native_unit_of_measurement=UnitOfLength.KILOMETERS,
		state_class=SensorStateClass.TOTAL_INCREASING,
		value_fn=lambda d: d.telemetry.odometer,
	),
	EbmxSensorDescription(
		key="fault",
		translation_key="fault",
		entity_category=EntityCategory.DIAGNOSTIC,
		value_fn=lambda d: d.telemetry.fault,
	),
)


async def async_setup_entry(
	hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
	"""Set up EBMX sensors for a bike."""
	coordinator: EbmxCoordinator = hass.data[DOMAIN][entry.entry_id]
	_LOGGER.debug("Setting up %d EBMX sensors for entry_id=%s", len(SENSORS), entry.entry_id)
	async_add_entities(EbmxSensor(coordinator, desc) for desc in SENSORS)


class EbmxSensor(EbmxEntity, RestoreSensor):
	"""A telemetry sensor that keeps showing its last value when the bike is away.

	Value resolution order: the coordinator's latest reading if present, otherwise the
	value restored from the previous Home Assistant session. The entity stays available
	as long as we have *any* value, so cached data keeps displaying; presence is exposed
	separately by the connectivity binary_sensor.
	"""

	entity_description: EbmxSensorDescription

	def __init__(self, coordinator: EbmxCoordinator, description: EbmxSensorDescription) -> None:
		super().__init__(coordinator, description.key)
		self.entity_description = description
		self._restored_value: float | int | None = None

	async def async_added_to_hass(self) -> None:
		await super().async_added_to_hass()
		if (last := await self.async_get_last_sensor_data()) is not None:
			self._restored_value = last.native_value
			_LOGGER.debug("%s restored value=%s", self.entity_id, self._restored_value)
		else:
			_LOGGER.debug("%s no restored value", self.entity_id)

	@property
	def native_value(self) -> float | int | None:
		if self.coordinator.data is not None:
			value = self.entity_description.value_fn(self.coordinator.data)
			_LOGGER.debug(
				"%s native_value from coordinator data=%s",
				self.entity_id,
				value,
			)
			return value
		_LOGGER.debug(
			"%s native_value from restored value=%s",
			self.entity_id,
			self._restored_value,
		)
		return self._restored_value

	@property
	def available(self) -> bool:
		# Keep displaying cached/restored values even when the bike isn't present.
		result = self.coordinator.data is not None or self._restored_value is not None
		_LOGGER.debug(
			"%s available=%s coordinator_has_data=%s restored_value=%s",
			self.entity_id,
			result,
			self.coordinator.data is not None,
			self._restored_value,
		)
		return result

	@callback
	def _handle_coordinator_update(self) -> None:
		# A fresh reading supersedes any restored value.
		self._restored_value = None
		_LOGGER.debug(
			"%s coordinator update available=%s value=%s",
			self.entity_id,
			self.available,
			self.native_value,
		)
		super()._handle_coordinator_update()
