from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Set up DayBetter effect category and effect select entities."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = []
    for device_id in coordinator.data:
        entities.append(DayBetterEffectCategorySelect(coordinator, device_id))
        entities.append(DayBetterEffectSelect(coordinator, device_id))
    async_add_entities(entities)


class DayBetterEffectCategorySelect(DayBetterEntity, SelectEntity):
    """Select entity to filter effects by category."""

    _attr_translation_key = "effect_category"
    _attr_icon = "mdi:folder-star-outline"

    def __init__(
        self,
        coordinator: DayBetterDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_effect_category"

    @property
    def options(self) -> list[str]:
        return self.coordinator.get_effect_catalog(self._device.mold_pid).categories

    @property
    def current_option(self) -> str | None:
        options = self.options
        if not options:
            return None
        if self._device.effect_category in options:
            return self._device.effect_category
        return options[0]

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_effect_category(self._device_id, option)


class DayBetterEffectSelect(DayBetterEntity, SelectEntity):
    """Select entity showing effects within the chosen category."""

    _attr_translation_key = "effect"
    _attr_icon = "mdi:palette-swatch-outline"

    def __init__(
        self,
        coordinator: DayBetterDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_effect"

    def _active_category(self) -> str | None:
        catalog = self.coordinator.get_effect_catalog(self._device.mold_pid)
        if not catalog.categories:
            return None
        if self._device.effect_category in catalog.by_category:
            return self._device.effect_category
        return catalog.categories[0]

    @property
    def options(self) -> list[str]:
        category = self._active_category()
        if not category:
            return []
        return self.coordinator.get_effect_catalog(
            self._device.mold_pid
        ).effects_in_category(category)

    @property
    def current_option(self) -> str | None:
        category = self._active_category()
        effect = self._device.effect
        if not category or not effect:
            return None
        prefix = f"{category}: "
        if effect.startswith(prefix):
            scene = effect.removeprefix(prefix)
            if scene in self.options:
                return scene
        return None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_category_effect(self._device_id, option)
