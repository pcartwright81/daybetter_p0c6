from __future__ import annotations

import json
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.daybetter_p0c6.api import DayBetterDevice
from custom_components.daybetter_p0c6.coordinator import DayBetterDataUpdateCoordinator


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.sent_json: list[dict[str, Any]] = []
        self.sent_str: list[str] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent_json.append(data)

    async def send_str(self, data: str) -> None:
        self.sent_str.append(data)

    async def close(self) -> None:
        self.closed = True


class _FakeApi:
    def __init__(self) -> None:
        self.token = "tok_test"
        self.power_calls: list[tuple[int, bool]] = []
        self.effects_calls = 0

    async def async_get_devices(self, group_id: int) -> list[DayBetterDevice]:
        return [
            DayBetterDevice(
                device_id=100002,
                topic="DEVTOPIC0002",
                name="Desk Lamp",
                online=False,
                is_on=False,
                mac="AA:BB:CC:DD:EE:03",
                wlan_mac="AA:BB:CC:DD:EE:04",
                mold_pid="P0C6",
            )
        ]

    async def async_get_all_effects(self, device_pid: str) -> dict[str, str]:
        self.effects_calls += 1
        return {"Christmas": "A009042270FF", "Pleasure": "A0090428F0F8"}

    async def async_set_power(self, device_id: int, is_on: bool) -> None:
        self.power_calls.append((device_id, is_on))


async def _make_coordinator() -> tuple[
    DayBetterDataUpdateCoordinator, _FakeApi, _FakeWebSocket
]:
    api = _FakeApi()
    ws = _FakeWebSocket()
    coordinator = DayBetterDataUpdateCoordinator(
        hass=HomeAssistant(),
        config_entry=ConfigEntry(),
        api=api,  # type: ignore[arg-type]
        session=None,  # type: ignore[arg-type]
        user_group=1000001,
    )
    coordinator._ws = ws  # type: ignore[assignment]
    coordinator.data = await coordinator._async_update_data()
    return coordinator, api, ws


async def test_ws_inbound_availability_and_acks() -> None:
    coordinator, _, _ = await _make_coordinator()
    device = coordinator.data[100002]
    assert device.online is False

    coordinator.handle_ws_message("heart")
    assert device.online is False

    coordinator.handle_ws_message(
        json.dumps(
            {
                "code": "1",
                "data": {
                    "desired": {"data": "1", "type": "4"},
                    "deviceName": "DEVTOPIC0002",
                },
            }
        )
    )
    assert coordinator.data[100002].online is True

    coordinator.handle_ws_message(
        json.dumps(
            {
                "code": "1",
                "data": {
                    "desired": {"data": "0", "type": "4"},
                    "deviceName": "DEVTOPIC0002",
                },
            }
        )
    )
    assert coordinator.data[100002].online is True

    coordinator.handle_ws_message(
        json.dumps(
            {
                "code": "1",
                "data": {
                    "desired": {"data": "a1040401a119", "type": 2},
                    "deviceName": "DEVTOPIC0002",
                },
            }
        )
    )
    assert coordinator.data[100002].last_ack == "A1040401A119"


async def test_ws_command_dispatch_rgb_effect_and_raw() -> None:
    coordinator, _, ws = await _make_coordinator()
    ws.sent_json.clear()

    await coordinator.async_set_rgb(100002, (0x66, 0x66, 0xFF), brightness=255)
    assert len(ws.sent_json) == 1
    rgb_msg = ws.sent_json[0]
    assert rgb_msg["topic"] == "DEVTOPIC0002"
    assert rgb_msg["type"] == 2
    assert rgb_msg["groupId"] == ""
    assert rgb_msg["classify"] == 0
    assert rgb_msg["data"] == "A0041A6666FF0102030405060708090A0B0C0D0E0F10111213144FC1"
    assert coordinator.data[100002].is_on is True
    assert coordinator.data[100002].rgb_color == (0x66, 0x66, 0xFF)

    await coordinator.async_set_effect(100002, "Christmas")
    assert ws.sent_json[1]["data"] == "A009042270FF"
    assert coordinator.data[100002].effect == "Christmas"

    await coordinator.async_send_raw_command(100002, "a0 10 04 01 e0 e1")
    assert ws.sent_json[2]["data"] == "A0100401E0E1"

    with pytest.raises(HomeAssistantError):
        await coordinator.async_send_raw_command(100002, "NOT_HEX")


async def test_ws_power_and_status_dump_parsing() -> None:
    coordinator, _, ws = await _make_coordinator()
    ws.sent_json.clear()

    await coordinator.async_set_power(100002, True)
    assert ws.sent_json[0]["data"] == "A0110401B121"
    assert coordinator.data[100002].is_on is True

    await coordinator.async_set_power(100002, False)
    assert ws.sent_json[1]["data"] == "A011040070E1"
    assert coordinator.data[100002].is_on is False

    status_dump = (
        "A1106C01C8006432320000"
        + "FF0FE764" * 20
        + "01000001010002140058010000020000014852"
    )
    coordinator.handle_ws_message(
        json.dumps(
            {
                "code": "1",
                "data": {
                    "desired": {"data": status_dump, "type": 2},
                    "deviceName": "DEVTOPIC0002",
                },
            }
        )
    )
    device = coordinator.data[100002]
    assert device.is_on is True
    assert device.brightness == 255
    assert device.rgb_color == (255, 15, 231)


async def test_update_preserves_runtime_state_and_caches_effects() -> None:
    coordinator, api, _ = await _make_coordinator()
    await coordinator.async_set_rgb(100002, (0x99, 0x33, 0xFF), brightness=200)
    assert api.effects_calls == 1

    refreshed = await coordinator._async_update_data()
    assert api.effects_calls == 1
    assert refreshed[100002].rgb_color == (0x99, 0x33, 0xFF)
    assert refreshed[100002].brightness == 200
