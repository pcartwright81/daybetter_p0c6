from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DayBetterDevice
from .const import DOMAIN
from .coordinator import DayBetterDataUpdateCoordinator


class DayBetterEntity(CoordinatorEntity[DayBetterDataUpdateCoordinator]):
    """Base entity for DayBetter P0C6 devices."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DayBetterDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def _device(self) -> DayBetterDevice:
        return self.coordinator.data[self._device_id]

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        connections: set[tuple[str, str]] = set()
        if device.wlan_mac:
            connections.add((dr.CONNECTION_NETWORK_MAC, device.wlan_mac))
        return DeviceInfo(
            identifiers={(DOMAIN, str(device.device_id))},
            connections=connections,
            name=device.name,
            manufacturer="DayBetter",
            model=device.mold_pid,
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self._device.online
        )
