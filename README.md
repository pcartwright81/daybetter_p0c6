# DayBetter P0C6 Tap Lamp for Home Assistant

HACS-compatible Home Assistant custom integration (`daybetter_p0c6`) for controlling DayBetter Wi-Fi Tap Lamps (`deviceMoldPid: "P0C6"`, `deviceType: 56`, `deviceSubclass: 2`) over the DayBetter cloud REST API and real-time WebSocket protocol (`cloud_push`).

## Features

- **Authentication**: Sign in with Email + 6-digit OTP code or paste an existing `userToken`, with automatic re-authentication support when tokens expire.
- **Power Control**: On/off control via the DayBetter cloud API.
- **RGB Color & Brightness**: Solid RGB color frames generated with CRC-16/Modbus (`poly=0xA001`, `init=0xFFFF`, little-endian) and sent over the real-time WebSocket.
- **Dynamic Scene & Rhythm Effects**: Automatically fetches Classic, Edition (Static, Festival, Moods, Landscapes, Life), and Rhythm presets into the light's `effect_list`.
- **Real-Time WebSocket Client**: Persistent background connection with 20-second `"heart"` keepalive, automatic exponential reconnect backoff, topic subscriptions, and ACK/availability handling.
- **Developer Action**: `daybetter_p0c6.send_raw_command` action for testing raw hex frames directly from **Developer Tools → Actions**.

## Installation

### Via HACS (Custom Repository)

1. Open **HACS** in Home Assistant.
2. Open the menu (⋮) → **Custom repositories**.
3. Add this repository URL with category **Integration**.
4. Search for **DayBetter P0C6 Tap Lamp** and click **Download**.
5. Restart Home Assistant.

### Manual Installation

Copy `custom_components/daybetter_p0c6` into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **DayBetter P0C6 Tap Lamp**.
3. Choose either:
   - **Sign in with Email + OTP code** (enter your email, then the 6-digit code sent to your inbox), or
   - **Paste existing userToken** (validated automatically against `/user/app/getAppUser`).

## Developer Action: `daybetter_p0c6.send_raw_command`

```yaml
action: daybetter_p0c6.send_raw_command
data:
  entity_id: light.desk_lamp
  hex_data: "A0100401E0E1"
```

## Development & Testing

```bash
uv run --with pytest --with pytest-asyncio --with aiohttp --with voluptuous pytest
```
