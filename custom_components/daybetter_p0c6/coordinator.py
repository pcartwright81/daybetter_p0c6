from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import time
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DayBetterApiClient,
    DayBetterAuthError,
    DayBetterDevice,
    DayBetterError,
    build_rgb_command,
    ensure_crc16,
    verify_crc16,
)
from .const import (
    APP_VERSION,
    CMD_POWER_OFF,
    CMD_POWER_ON,
    CMD_QUERY_STATE,
    DOMAIN,
    LANGUAGE_TYPE,
    SCAN_INTERVAL,
    SYSTEM_MODEL,
    USER_AGENT,
    WS_HEARTBEAT_INTERVAL,
    WS_RECONNECT_MAX_DELAY,
    WS_RECONNECT_MIN_DELAY,
    WS_URL_TEMPLATE,
)

_LOGGER = logging.getLogger(__name__)


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _scale_rgb(
    rgb_color: tuple[int, int, int], brightness: int | None
) -> tuple[int, int, int]:
    if brightness is None or brightness >= 255:
        return rgb_color
    factor = max(0, min(255, brightness)) / 255.0
    return (
        round(rgb_color[0] * factor),
        round(rgb_color[1] * factor),
        round(rgb_color[2] * factor),
    )


class DayBetterDataUpdateCoordinator(DataUpdateCoordinator[dict[int, DayBetterDevice]]):
    """Coordinator managing DayBetter REST polling and real-time WebSocket push."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: DayBetterApiClient,
        session: aiohttp.ClientSession,
        user_group: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self._session = session
        self.user_group = user_group
        self.effects_by_pid: dict[str, dict[str, str]] = {}
        self._topic_to_device_id: dict[str, int] = {}
        self._subscribed_topics: set[str] = set()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._ws_send_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[int, DayBetterDevice]:
        try:
            devices = await self.api.async_get_devices(self.user_group)
        except DayBetterAuthError as err:
            raise ConfigEntryAuthFailed(
                f"DayBetter authentication failed: {err}"
            ) from err
        except DayBetterError as err:
            raise UpdateFailed(
                f"Error communicating with DayBetter API: {err}"
            ) from err

        previous = self.data or {}
        result: dict[int, DayBetterDevice] = {}
        new_topics: list[str] = []

        for device in devices:
            if old := previous.get(device.device_id):
                device.rgb_color = old.rgb_color
                device.brightness = old.brightness
                device.effect = old.effect
                device.last_ack = old.last_ack

            result[device.device_id] = device
            if device.topic:
                self._topic_to_device_id[device.topic] = device.device_id
                if device.topic not in self._subscribed_topics:
                    new_topics.append(device.topic)

            if device.mold_pid not in self.effects_by_pid:
                self.effects_by_pid[
                    device.mold_pid
                ] = await self.api.async_get_all_effects(device.mold_pid)

        if self._ws is not None and not self._ws.closed and new_topics:
            for topic in new_topics:
                with suppress(HomeAssistantError):
                    await self._async_subscribe_topic(topic)

        return result

    def get_effects_for_pid(self, mold_pid: str) -> dict[str, str]:
        """Return cached {effect_name: HEX_COMMAND} map for a device PID."""
        return self.effects_by_pid.get(mold_pid, {})

    def async_start_websocket(self) -> None:
        """Start the resilient background WebSocket listener task."""
        if self._ws_task is not None and not self._ws_task.done():
            return
        self._stop_event.clear()
        self._ws_task = self.hass.async_create_background_task(
            self._async_ws_loop(),
            name=f"{DOMAIN}_websocket",
        )

    async def async_stop_websocket(self) -> None:
        """Unsubscribe active topics and stop the WebSocket task."""
        self._stop_event.set()
        if self._ws is not None and not self._ws.closed:
            for topic in list(self._subscribed_topics):
                with suppress(Exception):
                    await self._async_unsubscribe_topic(topic)
            with suppress(Exception):
                await self._ws.close()
        self._subscribed_topics.clear()
        if self._ws_task is not None:
            self._ws_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        self._ws = None

    async def _async_ws_loop(self) -> None:
        backoff = WS_RECONNECT_MIN_DELAY
        while not self._stop_event.is_set():
            token = self.api.token
            if not token:
                await asyncio.sleep(backoff)
                continue

            url = WS_URL_TEMPLATE.format(token=token)
            headers = {
                "appVersion": APP_VERSION,
                "languageType": LANGUAGE_TYPE,
                "systemModel": SYSTEM_MODEL,
                "User-Agent": USER_AGENT,
            }
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                async with self._session.ws_connect(
                    url,
                    headers=headers,
                    autoping=True,
                ) as ws:
                    self._ws = ws
                    self._subscribed_topics.clear()
                    backoff = WS_RECONNECT_MIN_DELAY
                    _LOGGER.debug("Connected to DayBetter WebSocket")

                    await self._async_subscribe_all()
                    heartbeat_task = asyncio.create_task(self._async_heartbeat_loop(ws))

                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self.handle_ws_message(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            _LOGGER.debug("DayBetter WebSocket closed: %s", msg.type)
                            break
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug("DayBetter WebSocket error: %s", err)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat_task
                self._ws = None
                self._subscribed_topics.clear()

            if self._stop_event.is_set():
                break

            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
            backoff = min(backoff * 2, WS_RECONNECT_MAX_DELAY)

    async def _async_heartbeat_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not self._stop_event.is_set() and not ws.closed:
            await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
            if ws.closed or self._stop_event.is_set():
                break
            async with self._ws_send_lock:
                await ws.send_str("heart")

    async def _async_subscribe_all(self) -> None:
        for device in (self.data or {}).values():
            if not device.topic:
                continue
            await self._async_subscribe_topic(device.topic)

    async def _async_subscribe_topic(self, topic: str) -> None:
        await self._async_send_ws_json(
            {
                "data": "",
                "topic": topic,
                "time": _epoch_ms(),
                "type": 0,
                "classify": 0,
            }
        )
        self._subscribed_topics.add(topic)
        await self.async_send_ws_command(topic, CMD_QUERY_STATE)

    async def _async_unsubscribe_topic(self, topic: str) -> None:
        await self._async_send_ws_json(
            {
                "data": "",
                "topic": topic,
                "time": _epoch_ms(),
                "type": 1,
                "classify": 0,
            }
        )
        self._subscribed_topics.discard(topic)

    async def _async_send_ws_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed:
            raise HomeAssistantError("DayBetter WebSocket is not connected")
        async with self._ws_send_lock:
            await self._ws.send_json(payload)

    async def async_send_ws_command(self, topic: str, hex_command: str) -> None:
        """Send a type-2 hex command frame over the WebSocket."""
        cleaned = hex_command.strip().upper()
        _LOGGER.debug("Sending WebSocket command to %s: %s", topic, cleaned)
        await self._async_send_ws_json(
            {
                "data": cleaned,
                "topic": topic,
                "groupId": "",
                "time": _epoch_ms(),
                "type": 2,
                "classify": 0,
            }
        )

    def handle_ws_message(self, raw_message: str) -> None:
        """Parse an inbound WebSocket text message and update coordinator state."""
        text = raw_message.strip()
        if not text or text == "heart":
            return

        try:
            payload = json.loads(text)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON WebSocket frame: %s", text)
            return

        if not isinstance(payload, dict):
            return

        data = payload.get("data")
        if not isinstance(data, dict):
            return

        topic = data.get("deviceName")
        desired = data.get("desired")
        if not topic or not isinstance(desired, dict):
            return

        device_id = self._topic_to_device_id.get(str(topic))
        if device_id is None or not self.data or device_id not in self.data:
            return

        device = self.data[device_id]
        msg_type = str(desired.get("type", ""))
        msg_data = desired.get("data")

        if msg_type == "4":
            if str(msg_data) == "1":
                if not device.online:
                    device.online = True
                    self.async_set_updated_data(dict(self.data))
            elif str(msg_data) == "0":
                _LOGGER.debug(
                    "Ignoring transient status '0' pulse for device %s (%s)",
                    device.device_id,
                    topic,
                )
            return

        if msg_type == "2" and msg_data is not None:
            ack = str(msg_data).strip().upper()
            device.last_ack = ack
            _LOGGER.debug(
                "Received WebSocket ACK for device %s (%s): %s",
                device.device_id,
                topic,
                ack,
            )
            self._apply_status_dump(device, ack)
            self.async_set_updated_data(dict(self.data))

    @staticmethod
    def _apply_status_dump(device: DayBetterDevice, hex_frame: str) -> None:
        if not hex_frame.startswith("A110"):
            return
        try:
            raw = bytes.fromhex(hex_frame)
        except ValueError:
            return
        if len(raw) < 15 or not verify_crc16(raw):
            return
        device.is_on = raw[3] == 1
        bri_pct = max(0, min(100, raw[6]))
        device.brightness = round(bri_pct * 255 / 100)
        device.rgb_color = (raw[11], raw[12], raw[13])

    async def async_set_power(self, device_id: int, is_on: bool) -> None:
        """Set device power state via WebSocket (with REST fallback)."""
        device = self.data.get(device_id) if self.data else None
        if (
            device is not None
            and device.topic
            and self._ws is not None
            and not self._ws.closed
        ):
            hex_cmd = CMD_POWER_ON if is_on else CMD_POWER_OFF
            await self.async_send_ws_command(device.topic, hex_cmd)
        else:
            try:
                await self.api.async_set_power(device_id, is_on)
            except DayBetterAuthError as err:
                self.config_entry.async_start_reauth(self.hass)
                raise HomeAssistantError(f"Authentication error: {err}") from err
            except DayBetterError as err:
                raise HomeAssistantError(f"Failed to set power state: {err}") from err

        if self.data and device_id in self.data:
            self.data[device_id].is_on = is_on
            self.async_set_updated_data(dict(self.data))

    async def async_set_rgb(
        self,
        device_id: int,
        rgb_color: tuple[int, int, int],
        brightness: int | None = None,
    ) -> None:
        """Send a solid RGB color frame over WebSocket."""
        device = self._require_device(device_id)
        effective_brightness = (
            brightness if brightness is not None else (device.brightness or 255)
        )
        scaled = _scale_rgb(rgb_color, effective_brightness)
        hex_cmd = build_rgb_command(*scaled)
        await self.async_send_ws_command(device.topic, hex_cmd)
        device.is_on = True
        device.rgb_color = rgb_color
        device.brightness = effective_brightness
        device.effect = None
        if self.data:
            self.async_set_updated_data(dict(self.data))

    async def async_set_effect(self, device_id: int, effect: str) -> None:
        """Activate a scene or rhythm effect preset over WebSocket."""
        device = self._require_device(device_id)
        effects = self.get_effects_for_pid(device.mold_pid)
        raw_cmd = effects.get(effect)
        if not raw_cmd:
            raise HomeAssistantError(
                f"Unknown effect '{effect}' for device {device.name}"
            )
        try:
            hex_cmd = ensure_crc16(raw_cmd)
        except ValueError as err:
            raise HomeAssistantError(
                f"Effect '{effect}' does not have a valid hex command"
            ) from err
        await self.async_send_ws_command(device.topic, hex_cmd)
        device.is_on = True
        device.effect = effect
        if self.data:
            self.async_set_updated_data(dict(self.data))

    async def async_send_raw_command(self, device_id: int, hex_data: str) -> None:
        """Validate and send an arbitrary raw hex command over WebSocket."""
        device = self._require_device(device_id)
        cleaned = hex_data.strip().replace(" ", "").upper()
        try:
            bytes.fromhex(cleaned)
        except ValueError as err:
            raise HomeAssistantError(f"Invalid hex payload: {hex_data}") from err
        if not cleaned:
            raise HomeAssistantError("Hex payload cannot be empty")
        await self.async_send_ws_command(device.topic, cleaned)

    def _require_device(self, device_id: int) -> DayBetterDevice:
        if not self.data or device_id not in self.data:
            raise HomeAssistantError(f"Unknown DayBetter device ID: {device_id}")
        device = self.data[device_id]
        if not device.topic:
            raise HomeAssistantError(
                f"Device {device.name} is missing a WebSocket topic"
            )
        return device
