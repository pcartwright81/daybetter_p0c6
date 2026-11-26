from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
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
    """Set up DayBetter light entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        DayBetterLightEntity(coordinator, device_id) for device_id in coordinator.data
    )


class DayBetterLightEntity(DayBetterEntity, LightEntity):
    """Representation of a DayBetter P0C6 Wi-Fi Tap Lamp."""

    _attr_name = None
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.RGB}

    def __init__(
        self,
        coordinator: DayBetterDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{DOMAIN}_{device_id}"

    @property
    def is_on(self) -> bool:
        return self._device.is_on

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        if self._device.effect:
            return None
        return self._device.rgb_color

    @property
    def brightness(self) -> int | None:
        return self._device.brightness

    @property
    def effect(self) -> str | None:
        return self._device.effect

    @property
    def effect_list(self) -> list[str] | None:
        effects = self.coordinator.get_effects_for_pid(self._device.mold_pid)
        return list(effects) if effects else None

    @property
    def supported_features(self) -> LightEntityFeature:
        if self.effect_list:
            return LightEntityFeature.EFFECT
        return LightEntityFeature(0)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the lamp and optionally set RGB color, brightness, or effect."""
        effect: str | None = kwargs.get(ATTR_EFFECT)
        rgb_color: tuple[int, int, int] | None = kwargs.get(ATTR_RGB_COLOR)
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)

        if not self._device.is_on or (
            effect is None and rgb_color is None and brightness is None
        ):
            await self.coordinator.async_set_power(self._device_id, True)

        if effect is not None:
            await self.coordinator.async_set_effect(self._device_id, effect)
            return

        if rgb_color is not None or brightness is not None:
            target_rgb = rgb_color or self._device.rgb_color or (255, 255, 255)
            await self.coordinator.async_set_rgb(
                self._device_id,
                target_rgb,
                brightness=brightness,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the lamp."""
        await self.coordinator.async_set_power(self._device_id, False)
