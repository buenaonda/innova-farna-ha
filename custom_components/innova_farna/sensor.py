"""Sensor platform: ambient temperature & humidity reported by the unit."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


@dataclass(frozen=True, kw_only=True)
class InnovaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[object], float | None]


SENSORS: tuple[InnovaSensorDescription, ...] = (
    InnovaSensorDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda st: round(st.air_temperature, 1),
    ),
    InnovaSensorDescription(
        key="air_humidity",
        translation_key="air_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda st: round(st.air_humidity) if st.air_humidity else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        InnovaSensor(coordinator, dev, desc)
        for dev in coordinator.devices
        for desc in SENSORS
    )


class InnovaSensor(InnovaEntity, SensorEntity):
    entity_description: InnovaSensorDescription

    def __init__(self, coordinator, device, description: InnovaSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device.mac_address}_{device.node_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        st = self._state
        return self.entity_description.value_fn(st) if st else None
