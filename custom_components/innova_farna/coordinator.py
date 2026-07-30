"""Data update coordinator: polls per-device state from the Innova cloud."""
from __future__ import annotations

import logging

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
from .const import DOMAIN, SCAN_INTERVAL

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

    async def _async_login(self) -> None:
        await self.client.login(
            self.config_entry.data[CONF_EMAIL], self.config_entry.data[CONF_PASSWORD]
        )

    async def _async_setup(self) -> None:
        try:
            await self._async_login()
            self.devices = await self.client.list_devices()
        except InnovaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except InnovaError as err:
            raise UpdateFailed(str(err)) from err
        if not self.devices:
            _LOGGER.warning("Innova account has no devices")

    async def _fetch_states(self) -> StateMap:
        if not self.devices:
            self.devices = await self.client.list_devices()
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
