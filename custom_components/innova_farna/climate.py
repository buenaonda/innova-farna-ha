"""Climate platform for Innova FÄRNA."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FAN_TO_HA,
    HA_TO_FAN,
    HA_TO_HVAC_MODE,
    HVAC_MODE_TO_HA,
    MAX_TEMP,
    MIN_TEMP,
    TARGET_TEMP_STEP,
)
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: InnovaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(InnovaClimate(coordinator, dev) for dev in coordinator.devices)


class InnovaClimate(InnovaEntity, ClimateEntity):
    """An Innova FÄRNA air conditioner as a climate entity."""

    _attr_name = None  # use the device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TARGET_TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_MODE_TO_HA.values()]
    _attr_fan_modes = list(FAN_TO_HA.values())
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: InnovaCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.mac_address}_{device.node_id}_climate"

    @property
    def current_temperature(self) -> float | None:
        st = self._state
        return round(st.air_temperature, 1) if st else None

    @property
    def current_humidity(self) -> int | None:
        st = self._state
        return int(st.air_humidity) if st and st.air_humidity else None

    @property
    def target_temperature(self) -> float | None:
        st = self._state
        return st.temperature_setpoint if st else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        st = self._state
        if st is None:
            return None
        if not st.power:
            return HVACMode.OFF
        return HVAC_MODE_TO_HA.get(st.hvac_mode, HVACMode.AUTO)

    @property
    def fan_mode(self) -> str | None:
        st = self._state
        return FAN_TO_HA.get(st.fan_speed) if st else None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self.coordinator.client.set_state(
            self._device.mac_address, self._device.node_id, temperature_setpoint=temp
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.client.set_state(
                self._device.mac_address, self._device.node_id, power=False
            )
        else:
            await self.coordinator.client.set_state(
                self._device.mac_address,
                self._device.node_id,
                power=True,
                hvac_mode=HA_TO_HVAC_MODE.get(hvac_mode),
            )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.client.set_state(
            self._device.mac_address,
            self._device.node_id,
            fan_speed=HA_TO_FAN.get(fan_mode),
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.coordinator.client.set_state(
            self._device.mac_address, self._device.node_id, power=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.coordinator.client.set_state(
            self._device.mac_address, self._device.node_id, power=False
        )
        await self.coordinator.async_request_refresh()
