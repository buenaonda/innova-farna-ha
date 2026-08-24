"""Climate platform for Innova FÄRNA."""
from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaError
from .const import (
    DOMAIN,
    FAN_TO_HA,
    HA_TO_FAN,
    HA_TO_HVAC_MODE,
    HVAC_MODE_TO_HA,
    FARNA_FAN_TO_HA,
    FARNA_HA_TO_FAN,
    FARNA_HA_TO_HVAC_MODE,
    FARNA_HVAC_MODE_TO_HA,
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
        async_add_entities(InnovaClimate(coordinator, dev) for dev in nuevos)

    entry.async_on_unload(coordinator.async_add_listener(_agregar_nuevos))
    _agregar_nuevos()


class InnovaClimate(InnovaEntity, ClimateEntity):
    """An Innova FÄRNA air conditioner as a climate entity."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    @property
    def hvac_modes(self) -> list[HVACMode]:
        st = self._state
        mapping = (
            FARNA_HVAC_MODE_TO_HA
            if st is not None and st.family == "fancoil"
            else HVAC_MODE_TO_HA
        )
        return [HVACMode.OFF, *mapping.values()]

    @property
    def fan_modes(self) -> list[str]:
        st = self._state
        mapping = (
            FARNA_FAN_TO_HA
            if st is not None and st.family == "fancoil"
            else FAN_TO_HA
        )
        return list(mapping.values())
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
    def min_temp(self) -> float:
        st = self._state
        return st.min_temp if st and st.min_temp else MIN_TEMP

    @property
    def max_temp(self) -> float:
        st = self._state
        return st.max_temp if st and st.max_temp else MAX_TEMP

    @property
    def target_temperature_step(self) -> float:
        st = self._state
        return st.temp_step if st and st.temp_step else TARGET_TEMP_STEP

    @property
    def current_temperature(self) -> float | None:
        st = self._state
        return st.current_temperature if st else None

    @property
    def target_temperature(self) -> float | None:
        st = self._state
        return st.target_temperature if st else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        st = self._state
        if st is None:
            return None
        if not st.power:
            return HVACMode.OFF
        return HVAC_MODE_TO_HA.get(st.hvac_mode)

    @property
    def fan_mode(self) -> str | None:
        st = self._state
        if st is None:
            return None
        mapping = FARNA_FAN_TO_HA if st.family == "fancoil" else FAN_TO_HA
        return mapping.get(st.fan_speed)

    async def _command(self, optimistic: dict[str, Any], **kwargs: Any) -> None:
        """Send a set_state, optimistically update local state, then refresh."""
        try:
            await self.coordinator.client.set_state(
                self._device.mac_address, self._device.node_id, **kwargs
            )
        except InnovaError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
        st = self._state
        if st is not None and optimistic:
            self.coordinator.data[self._key] = dataclasses.replace(st, **optimistic)
            self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self._command({"target_temperature": temp}, temperature_setpoint=temp)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._command({"power": False}, power=False)
        else:
            st = self._state
            mapping = (
                FARNA_HA_TO_HVAC_MODE
                if st is not None and st.family == "fancoil"
                else HA_TO_HVAC_MODE
            )
            mode = mapping.get(hvac_mode)
            if mode is None:
                raise HomeAssistantError(f"Unsupported HVAC mode: {hvac_mode}")
            await self._command(
                {"power": True, "hvac_mode": mode},
                power=True,
                hvac_mode=mode,
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        st = self._state
        mapping = (
            FARNA_HA_TO_FAN
            if st is not None and st.family == "fancoil"
            else HA_TO_FAN
        )
        fan = mapping.get(fan_mode)
        if fan is None:
            raise HomeAssistantError(f"Unsupported fan mode: {fan_mode}")
        await self._command(
            {"fan_speed": fan},
            fan_speed=fan,
        )

    async def async_turn_on(self) -> None:
        await self._command({"power": True}, power=True)

    async def async_turn_off(self) -> None:
        await self._command({"power": False}, power=False)
