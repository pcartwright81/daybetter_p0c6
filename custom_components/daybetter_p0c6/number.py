from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DayBetterConfigEntry
from .const import DOMAIN
from .coordinator import DayBetterDataUpdateCoordinator
from .entity import DayBetterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DayBetterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DayBetter effect speed number entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        DayBetterEffectSpeedNumber(coordinator, device_id)
        for device_id in coordinator.data
    )


class DayBetterEffectSpeedNumber(DayBetterEntity, NumberEntity):
    """Number slider controlling Classic scene animation speed (1-100%)."""

    _attr_translation_key = "effect_speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 1.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: DayBetterDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_effect_speed"

    @property
    def native_value(self) -> float:
        return float(self._device.effect_speed)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_effect_speed(self._device_id, int(value))
