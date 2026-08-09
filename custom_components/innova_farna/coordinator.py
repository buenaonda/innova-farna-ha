"""Data update coordinator: polls per-device state from the Innova cloud."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AcState,
    Device,
    InnovaAuthError,
    InnovaClient,
    InnovaDeviceOffline,
    InnovaError,
)
from .const import DEVICE_REFRESH_INTERVAL, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

StateMap = dict[tuple[str, int], AcState | None]


class InnovaCoordinator(DataUpdateCoordinator[StateMap]):
    """Keeps a map {(mac, node): AcState|None} fresh for all account devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = InnovaClient(session=async_get_clientsession(hass))
        self.devices: list[Device] = []
        self._devices_refreshed_at: datetime | None = None

    async def _async_login(self) -> None:
        await self.client.login(
            self.config_entry.data[CONF_EMAIL], self.config_entry.data[CONF_PASSWORD]
        )

    async def _async_setup(self) -> None:
        try:
            await self._async_login()
            await self._refresh_devices()
        except InnovaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except InnovaError as err:
            raise UpdateFailed(str(err)) from err
        if not self.devices:
            _LOGGER.warning("Innova account has no devices")

    async def _refresh_devices(self) -> list[Device]:
        """Re-lee la lista de equipos de la cuenta y devuelve los NUEVOS.

        Antes esto se hacía una sola vez, al montar la integración, y solo se
        repetía si la lista había quedado vacía. Consecuencia: un aire agregado
        a la cuenta DESPUÉS del setup no aparecía nunca — no es que tardara, es
        que nadie volvía a preguntar. Había que recargar la integración a mano.
        """
        conocidos = {(d.mac_address, d.node_id) for d in self.devices}
        self.devices = await self.client.list_devices()
        self._devices_refreshed_at = datetime.now(timezone.utc)
        nuevos = [d for d in self.devices if (d.mac_address, d.node_id) not in conocidos]
        if nuevos and conocidos:
            # `and conocidos` evita anunciar como "nuevos" los del primer arranque.
            _LOGGER.info(
                "Innova: %d equipo(s) nuevo(s) en la cuenta: %s",
                len(nuevos),
                ", ".join(d.name or d.serial_number for d in nuevos),
            )
        return nuevos

    def _toca_redescubrir(self) -> bool:
        if not self.devices or self._devices_refreshed_at is None:
            return True
        return datetime.now(timezone.utc) - self._devices_refreshed_at >= DEVICE_REFRESH_INTERVAL

    async def _fetch_states(self) -> StateMap:
        if self._toca_redescubrir():
            try:
                await self._refresh_devices()
            except InnovaAuthError:
                raise  # la maneja _async_update_data con un re-login
            except InnovaError as err:
                # Que falle el redescubrimiento NO puede dejar sin estado a los
                # equipos que ya funcionan: se sigue con la lista conocida.
                _LOGGER.warning("Innova: no se pudo refrescar la lista de equipos: %s", err)
        states: StateMap = {}
        for dev in self.devices:
            key = (dev.mac_address, dev.node_id)
            try:
                states[key] = await self.client.get_state(dev.mac_address, dev.node_id)
            except InnovaAuthError:
                raise  # bubble up for a single re-login attempt
            except InnovaDeviceOffline as err:
                _LOGGER.debug("Device %s offline: %s", key, err)
                states[key] = None
            except InnovaError as err:
                _LOGGER.warning("Device %s error: %s", key, err)
                states[key] = None
        return states

    async def _async_update_data(self) -> StateMap:
        try:
            return await self._fetch_states()
        except InnovaAuthError:
            # token likely expired -> re-login once and retry
            try:
                await self._async_login()
                return await self._fetch_states()
            except InnovaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except InnovaError as err:
                raise UpdateFailed(f"re-login failed: {err}") from err
        except InnovaError as err:
            raise UpdateFailed(str(err)) from err
