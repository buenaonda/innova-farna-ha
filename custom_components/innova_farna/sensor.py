"""Sensor platform: ambient temperature reported by the unit."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Las entidades se crean de forma INCREMENTAL, no una sola vez.
    #
    # `async_setup_entry` corre una vez en la vida de la entrada de configuración.
    # Si acá se crean las entidades y nada más, un equipo que aparezca después
    # queda sin entidad hasta que alguien recargue la integración. Reteniendo
    # `async_add_entities` y escuchando al coordinador, los equipos nuevos se
    # materializan solos en cuanto el coordinador los ve.
    vistos: set[tuple[str, int]] = set()

    @callback
    def _agregar_nuevos() -> None:
        nuevos = [
            dev
            for dev in coordinator.devices
            if (dev.mac_address, dev.node_id) not in vistos
        ]
        if not nuevos:
            return
        vistos.update((d.mac_address, d.node_id) for d in nuevos)
        entities = []
        for dev in nuevos:
            entities.append(InnovaTemperatureSensor(coordinator, dev))
            entities.append(InnovaWifiSignalSensor(coordinator, dev))
        async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(_agregar_nuevos))
    _agregar_nuevos()


class InnovaTemperatureSensor(InnovaEntity, SensorEntity):
    """Ambient temperature measured by the unit."""

    _attr_translation_key = "air_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.mac_address}_{device.node_id}_air_temperature"

    @property
    def native_value(self) -> float | None:
        st = self._state
        return st.current_temperature if st else None


class InnovaWifiSignalSensor(InnovaEntity, SensorEntity):
    """Wi-Fi signal strength reported by the unit."""

    _attr_name = "Wi-Fi signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.mac_address}_{device.node_id}_wifi_signal"

    @property
    def native_value(self) -> int | None:
        st = self._state
        return st.wifi_rssi if st else None
