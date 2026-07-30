"""Data update coordinator: polls per-device state from the Innova cloud."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    Device,
    InnovaAuthError,
    InnovaClient,
    InnovaDeviceOffline,
    InnovaError,
)
from .const import CONF_EMAIL, CONF_PASSWORD, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class InnovaCoordinator(DataUpdateCoordinator[dict]):
    """Keeps a map {(mac, node): AcState|None} fresh for all account devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name="innova_farna", update_interval=SCAN_INTERVAL)
        self.entry = entry
        self.client = InnovaClient(session=async_get_clientsession(hass))
        self.devices: list[Device] = []

    async def _async_login(self) -> None:
        await self.client.login(
            self.entry.data[CONF_EMAIL], self.entry.data[CONF_PASSWORD]
        )

    async def _async_setup(self) -> None:
        await self._async_login()
        self.devices = await self.client.list_devices()

    async def _async_update_data(self) -> dict:
        try:
            if not self.devices:
                self.devices = await self.client.list_devices()
            states: dict[tuple[str, int], object | None] = {}
            for dev in self.devices:
                key = (dev.mac_address, dev.node_id)
                try:
                    states[key] = await self.client.get_state(dev.mac_address, dev.node_id)
                except InnovaDeviceOffline:
                    states[key] = None  # device not connected to the cloud right now
            return states
        except InnovaAuthError:
            # token likely expired -> re-login once and retry
            try:
                await self._async_login()
                self.devices = await self.client.list_devices()
                return {
                    (d.mac_address, d.node_id): await _safe_state(self.client, d)
                    for d in self.devices
                }
            except InnovaError as err:
                raise UpdateFailed(f"auth/refresh failed: {err}") from err
        except InnovaError as err:
            raise UpdateFailed(str(err)) from err


async def _safe_state(client: InnovaClient, dev: Device):
    try:
        return await client.get_state(dev.mac_address, dev.node_id)
    except InnovaDeviceOffline:
        return None
