from __future__ import annotations

from dataclasses import dataclass, field
import sys
import types
from typing import Any, Generic, TypeVar

_T = TypeVar("_T")


def _install_ha_stubs() -> None:
    if "homeassistant" in sys.modules:
        return
    try:
        __import__("homeassistant")
        return
    except ImportError:
        pass

    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    const = types.ModuleType("homeassistant.const")
    const.ATTR_ENTITY_ID = "entity_id"
    const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"

    class Platform(str):
        LIGHT = "light"

    const.Platform = Platform
    sys.modules["homeassistant.const"] = const

    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    sys.modules["homeassistant.exceptions"] = exceptions

    core = types.ModuleType("homeassistant.core")

    class Event:
        pass

    class ServiceCall:
        def __init__(self, data: dict[str, Any]) -> None:
            self.data = data

    class HomeAssistant:
        pass

    core.Event = Event
    core.ServiceCall = ServiceCall
    core.HomeAssistant = HomeAssistant
    sys.modules["homeassistant.core"] = core

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry(Generic[_T]):
        def __init__(self, data: dict[str, Any] | None = None) -> None:
            self.data = data or {}
            self.runtime_data: Any = None
            self.reauth_started = False

        def async_start_reauth(self, hass: Any) -> None:
            self.reauth_started = True

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs: Any) -> None:
            super().__init_subclass__()

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = dict[str, Any]
    sys.modules["homeassistant.config_entries"] = config_entries

    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    cv = types.ModuleType("homeassistant.helpers.config_validation")
    cv.entity_ids = lambda value: [value] if isinstance(value, str) else list(value)
    cv.string = str
    sys.modules["homeassistant.helpers.config_validation"] = cv

    er = types.ModuleType("homeassistant.helpers.entity_registry")
    er.async_get = lambda hass: None
    sys.modules["homeassistant.helpers.entity_registry"] = er

    dr = types.ModuleType("homeassistant.helpers.device_registry")
    dr.CONNECTION_NETWORK_MAC = "mac"

    @dataclass
    class DeviceInfo:
        identifiers: set[tuple[str, str]] = field(default_factory=set)
        connections: set[tuple[str, str]] = field(default_factory=set)
        name: str | None = None
        manufacturer: str | None = None
        model: str | None = None

    dr.DeviceInfo = DeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = dr

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = Any
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator(Generic[_T]):
        def __init__(
            self,
            hass: Any,
            logger: Any,
            *,
            config_entry: Any = None,
            name: str = "",
            update_interval: Any = None,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.config_entry = config_entry
            self.name = name
            self.update_interval = update_interval
            self.data: _T = None  # type: ignore[assignment]
            self.updated_count = 0

        def async_set_updated_data(self, data: _T) -> None:
            self.data = data
            self.updated_count += 1

    class CoordinatorEntity(Generic[_T]):
        def __init__(self, coordinator: _T) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return True

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.UpdateFailed = UpdateFailed
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    components = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components

    light = types.ModuleType("homeassistant.components.light")
    light.ATTR_BRIGHTNESS = "brightness"
    light.ATTR_EFFECT = "effect"
    light.ATTR_RGB_COLOR = "rgb_color"

    class ColorMode(str):
        RGB = "rgb"
        ONOFF = "onoff"

    class LightEntityFeature(int):
        EFFECT = 4

    class LightEntity:
        pass

    light.ColorMode = ColorMode
    light.LightEntityFeature = LightEntityFeature
    light.LightEntity = LightEntity
    sys.modules["homeassistant.components.light"] = light


_install_ha_stubs()
