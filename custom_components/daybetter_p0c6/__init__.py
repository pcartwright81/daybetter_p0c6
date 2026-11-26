from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import DayBetterApiClient
from .const import (
    ATTR_HEX_DATA,
    CONF_TOKEN,
    CONF_USER_GROUP,
    DOMAIN,
    SERVICE_SEND_RAW_COMMAND,
)
from .coordinator import DayBetterDataUpdateCoordinator

type DayBetterConfigEntry = ConfigEntry[DayBetterDataUpdateCoordinator]

PLATFORMS: list[Platform] = [Platform.LIGHT]

SERVICE_SEND_RAW_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_HEX_DATA): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: DayBetterConfigEntry) -> bool:
    """Set up DayBetter P0C6 from a config entry."""
    session = async_get_clientsession(hass)
    api = DayBetterApiClient(session, token=entry.data[CONF_TOKEN])
    coordinator = DayBetterDataUpdateCoordinator(
        hass=hass,
        config_entry=entry,
        api=api,
        session=session,
        user_group=int(entry.data[CONF_USER_GROUP]),
    )

    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start_websocket()
    entry.runtime_data = coordinator

    async def _async_stop_ws(_event: Event) -> None:
        await coordinator.async_stop_websocket()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_ws)
    )

    _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DayBetterConfigEntry) -> bool:
    """Unload a DayBetter P0C6 config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_stop_websocket()

    loaded_entries = [
        cfg
        for cfg in hass.config_entries.async_entries(DOMAIN)
        if cfg.entry_id != entry.entry_id and cfg.runtime_data is not None
    ]
    if not loaded_entries and hass.services.has_service(
        DOMAIN, SERVICE_SEND_RAW_COMMAND
    ):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_RAW_COMMAND)

    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RAW_COMMAND):
        return

    async def _async_handle_send_raw_command(call: ServiceCall) -> None:
        entity_ids: list[str] = call.data[ATTR_ENTITY_ID]
        hex_data: str = call.data[ATTR_HEX_DATA]
        registry = er.async_get(hass)

        for entity_id in entity_ids:
            entity_entry = registry.async_get(entity_id)
            if (
                entity_entry is None
                or entity_entry.platform != DOMAIN
                or entity_entry.config_entry_id is None
            ):
                raise HomeAssistantError(f"Entity {entity_id} is not a {DOMAIN} entity")
            config_entry = hass.config_entries.async_get_entry(
                entity_entry.config_entry_id
            )
            if config_entry is None or config_entry.runtime_data is None:
                raise HomeAssistantError(f"Config entry for {entity_id} is not loaded")
            prefix = f"{DOMAIN}_"
            if not entity_entry.unique_id.startswith(prefix):
                raise HomeAssistantError(f"Cannot determine device ID for {entity_id}")
            device_id = int(entity_entry.unique_id.removeprefix(prefix))
            coordinator: DayBetterDataUpdateCoordinator = config_entry.runtime_data
            await coordinator.async_send_raw_command(device_id, hex_data)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW_COMMAND,
        _async_handle_send_raw_command,
        schema=SERVICE_SEND_RAW_COMMAND_SCHEMA,
    )
