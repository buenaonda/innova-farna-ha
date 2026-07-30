"""Shared base entity for Innova FÄRNA."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device
from .const import DOMAIN, MANUFACTURER
from .coordinator import InnovaCoordinator


class InnovaEntity(CoordinatorEntity[InnovaCoordinator]):
    """Base entity bound to one (mac, node) device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: InnovaCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._device = device
        self._key = (device.mac_address, device.node_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device.mac_address}_{device.node_id}")},
            manufacturer=MANUFACTURER,
            name=device.name or "Innova",
            model="FÄRNA",
            serial_number=device.serial_number or None,
            suggested_area=device.room_name or None,
        )

    @property
    def _state(self):
        """Current AcState protobuf message, or None if the device is offline."""
        return (self.coordinator.data or {}).get(self._key)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._state is not None
