from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    APP_VERSION,
    DEFAULT_PID,
    DEVICE_VERSION,
    ENDPOINT_CONTROL_DEVICE,
    ENDPOINT_GET_APP_USER,
    ENDPOINT_GET_DEVICE,
    ENDPOINT_GET_MODEL_CLASS,
    ENDPOINT_GET_MODEL_CLASSICS,
    ENDPOINT_GET_MODEL_EDITION,
    ENDPOINT_GET_RHYTHM_MODEL,
    ENDPOINT_LOGIN_EMAIL,
    ENDPOINT_REQUEST_OTP,
    LANGUAGE_TYPE,
    RGB_FRAME_HEADER,
    RGB_FRAME_SEGMENTS,
    SYSTEM_MODEL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
_AUTH_ERROR_CODES = frozenset({401, 403, 1001, 1002, 1003, 1004, 10001, 10002})
_MODEL_CLASS_NAMES: dict[int, str] = {
    4: "Landscapes",
    5: "Life",
    6: "Festival",
    7: "Moods",
    8: "Classic",
    11: "Static",
}


@dataclass(slots=True)
class EffectCatalog:
    """Categorized and sorted effect presets for a device PID."""

    by_category: dict[str, dict[str, str]]
    flat: dict[str, str]

    @classmethod
    def from_categories(cls, raw: dict[str, dict[str, str]]) -> EffectCatalog:
        """Build a sorted EffectCatalog from {category: {name: HEX}}."""
        sorted_categories: dict[str, dict[str, str]] = {}
        flat: dict[str, str] = {}
        for category in sorted(raw):
            items = raw[category]
            if not items:
                continue
            sorted_items = dict(sorted(items.items(), key=lambda kv: kv[0].lower()))
            sorted_categories[category] = sorted_items
            for name, order in sorted_items.items():
                flat[f"{category}: {name}"] = order
        return cls(by_category=sorted_categories, flat=flat)

    @property
    def categories(self) -> list[str]:
        """Return sorted category names."""
        return list(self.by_category)

    def effects_in_category(self, category: str) -> list[str]:
        """Return sorted scene names for a category."""
        return list(self.by_category.get(category, ()))


class DayBetterError(Exception):
    """Base exception for DayBetter API errors."""


class DayBetterAuthError(DayBetterError):
    """Authentication or token validation error."""


class DayBetterConnectionError(DayBetterError):
    """Network or connection error."""


@dataclass(slots=True)
class DayBetterUser:
    """Authenticated DayBetter account profile."""

    token: str
    user_group: int
    user_name: str
    email: str


@dataclass(slots=True)
class DayBetterDevice:
    """Representation of a DayBetter Wi-Fi lamp."""

    device_id: int
    topic: str
    name: str
    online: bool
    is_on: bool
    mac: str | None
    wlan_mac: str | None
    mold_pid: str
    rgb_color: tuple[int, int, int] | None = None
    brightness: int | None = None
    effect: str | None = None
    effect_category: str | None = None
    effect_speed: int = 50
    last_ack: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> DayBetterDevice:
        """Create a device model from a getDevice list item."""
        device_id = int(payload["deviceId"])
        topic = str(payload.get("deviceName") or "")
        name = str(payload.get("deviceGroupName") or topic or f"DayBetter {device_id}")
        return cls(
            device_id=device_id,
            topic=topic,
            name=name,
            online=int(payload.get("deviceState", 0)) == 1,
            is_on=int(payload.get("deviceSwitchStatus", 0)) == 1,
            mac=_normalize_mac(payload.get("deviceMac")),
            wlan_mac=_normalize_mac(payload.get("deviceWlanMac")),
            mold_pid=str(payload.get("deviceMoldPid") or DEFAULT_PID),
        )


def _normalize_mac(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def crc16_modbus(data: bytes) -> int:
    """Calculate CRC-16/Modbus (poly 0xA001, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def append_crc16(payload: bytes) -> bytes:
    """Append 2-byte little-endian CRC-16/Modbus to a payload."""
    return payload + crc16_modbus(payload).to_bytes(2, "little")


def verify_crc16(frame: bytes) -> bool:
    """Verify trailing 2-byte little-endian CRC-16/Modbus on a frame."""
    if len(frame) < 3:
        return False
    expected = crc16_modbus(frame[:-2]).to_bytes(2, "little")
    return frame[-2:] == expected


def ensure_crc16(hex_command: str, speed: int = 50) -> str:
    """Ensure a hex command frame has expected payload length and CRC-16/Modbus."""
    cleaned = hex_command.strip().replace(" ", "").upper()
    raw = bytes.fromhex(cleaned)
    if len(raw) >= 3 and raw[0] == 0xA0:
        expected_len = raw[2]
        if len(raw) == expected_len + 2 and verify_crc16(raw):
            return cleaned
        if len(raw) < expected_len:
            missing = expected_len - len(raw)
            speed_byte = max(1, min(100, speed))
            pad = bytes([speed_byte] + [0x00] * (missing - 1))
            raw = raw + pad
        return append_crc16(raw).hex().upper()
    if len(raw) >= 3 and verify_crc16(raw):
        return cleaned
    return append_crc16(raw).hex().upper()


def build_rgb_command(red: int, green: int, blue: int) -> str:
    """Build an uppercase solid-RGB hex command with CRC-16/Modbus."""
    for channel in (red, green, blue):
        if not 0 <= channel <= 255:
            raise ValueError(f"RGB channel out of range: {channel}")
    payload = RGB_FRAME_HEADER + bytes((red, green, blue)) + RGB_FRAME_SEGMENTS
    return append_crc16(payload).hex().upper()


def _is_auth_failure(code: Any, message: str) -> bool:
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = None
    if numeric_code in _AUTH_ERROR_CODES:
        return True
    lowered = message.lower()
    return any(
        needle in lowered
        for needle in ("token", "unauthorized", "auth", "login", "expired")
    )


class DayBetterApiClient:
    """Async REST client for the DayBetter cloud API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._token = token

    @property
    def token(self) -> str | None:
        """Return the current bearer token."""
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        self._token = value

    def _base_headers(self, *, include_auth: bool = True) -> dict[str, str]:
        headers = {
            "appVersion": APP_VERSION,
            "languageType": LANGUAGE_TYPE,
            "systemModel": SYSTEM_MODEL,
            "User-Agent": USER_AGENT,
        }
        if include_auth and self._token:
            headers["Authorization"] = self._token
        return headers

    async def _post(
        self,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        form_empty: bool = False,
        include_auth: bool = True,
    ) -> Any:
        url = f"{API_BASE_URL}{endpoint}"
        headers = self._base_headers(include_auth=include_auth)
        kwargs: dict[str, Any] = {"headers": headers, "timeout": _REQUEST_TIMEOUT}

        if form_empty:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            kwargs["data"] = ""
        else:
            headers["Content-Type"] = "application/json; charset=utf-8"
            kwargs["json"] = json_body if json_body is not None else {}

        try:
            async with self._session.post(url, **kwargs) as response:
                if response.status in (401, 403):
                    raise DayBetterAuthError(
                        f"Authentication failed with HTTP {response.status}"
                    )
                if response.status >= 400:
                    raise DayBetterConnectionError(
                        f"HTTP {response.status} calling {endpoint}"
                    )
                body: dict[str, Any] = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise DayBetterConnectionError(
                f"Connection error calling {endpoint}: {err}"
            ) from err
        except ValueError as err:
            raise DayBetterError(f"Invalid JSON response from {endpoint}") from err

        code = body.get("code")
        message = str(body.get("message") or "")
        if code != 1:
            if _is_auth_failure(code, message):
                raise DayBetterAuthError(
                    f"Authentication error ({code}): {message or 'invalid token'}"
                )
            raise DayBetterError(
                f"API error on {endpoint} (code={code}): {message or 'unknown error'}"
            )
        return body.get("data")

    async def async_request_email_otp(self, email: str) -> None:
        """Request a 6-digit email login OTP."""
        await self._post(
            ENDPOINT_REQUEST_OTP,
            json_body={"accountType": 0, "userEmail": email},
            include_auth=False,
        )

    async def async_login_email(self, email: str, otp_code: str) -> DayBetterUser:
        """Verify email OTP and obtain a session token and user group."""
        data = await self._post(
            ENDPOINT_LOGIN_EMAIL,
            json_body={"code": otp_code.strip(), "account": email.strip()},
            include_auth=False,
        )
        if not isinstance(data, dict) or not data.get("userToken"):
            raise DayBetterAuthError("Login response missing userToken")

        token = str(data["userToken"])
        self._token = token
        user_group = int(data["userGroup"])
        user_name = str(data.get("userName") or email)
        user_email = str(data.get("userMailbox") or email)
        return DayBetterUser(
            token=token,
            user_group=user_group,
            user_name=user_name,
            email=user_email,
        )

    async def async_get_app_user(self) -> DayBetterUser:
        """Validate the current token and return account metadata."""
        if not self._token:
            raise DayBetterAuthError("No token configured")
        data = await self._post(
            ENDPOINT_GET_APP_USER,
            form_empty=True,
            include_auth=True,
        )
        if not isinstance(data, dict) or data.get("userGroup") is None:
            raise DayBetterAuthError("Token validation response missing userGroup")
        return DayBetterUser(
            token=self._token,
            user_group=int(data["userGroup"]),
            user_name=str(data.get("userName") or ""),
            email=str(data.get("userMailbox") or data.get("userName") or ""),
        )

    async def async_get_devices(self, group_id: int) -> list[DayBetterDevice]:
        """Fetch all devices belonging to a user group."""
        data = await self._post(
            ENDPOINT_GET_DEVICE,
            json_body={"groupId": group_id},
        )
        if not isinstance(data, list):
            return []
        return [
            DayBetterDevice.from_api(item)
            for item in data
            if isinstance(item, dict) and item.get("deviceId") is not None
        ]

    async def async_set_power(self, device_id: int, is_on: bool) -> None:
        """Turn a device on or off via the REST control endpoint."""
        await self._post(
            ENDPOINT_CONTROL_DEVICE,
            json_body={
                "deviceSwitchStatus": 1 if is_on else 0,
                "deviceId": device_id,
            },
        )

    async def async_get_model_classes(
        self, device_pid: str = DEFAULT_PID
    ) -> list[dict[str, Any]]:
        """Fetch scene category descriptors for a device PID."""
        data = await self._post(
            ENDPOINT_GET_MODEL_CLASS,
            json_body={
                "devicePid": device_pid,
                "versionNumber": APP_VERSION,
                "appLanguage": LANGUAGE_TYPE,
            },
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    async def async_get_classic_scenes(
        self, device_pid: str = DEFAULT_PID
    ) -> dict[str, str]:
        """Fetch classic scene presets mapped as {name: HEX_COMMAND}."""
        data = await self._post(
            ENDPOINT_GET_MODEL_CLASSICS,
            json_body={
                "devicePid": device_pid,
                "limit": 1000,
                "page": 1,
                "deviceVersion": DEVICE_VERSION,
                "versionNumber": APP_VERSION,
                "appLanguage": LANGUAGE_TYPE,
            },
        )
        effects: dict[str, str] = {}
        if not isinstance(data, dict):
            return effects
        for group in data.get("list") or []:
            if not isinstance(group, dict):
                continue
            for item in group.get("modelClassicsAppQoList") or []:
                if not isinstance(item, dict):
                    continue
                _add_effect(effects, item.get("modelName"), item.get("modelOrder"))
        return effects

    async def async_get_edition_scenes(
        self, model_class_id: int, device_pid: str = DEFAULT_PID
    ) -> dict[str, str]:
        """Fetch edition scenes for a specific model class ID."""
        data = await self._post(
            ENDPOINT_GET_MODEL_EDITION,
            json_body={
                "devicePid": device_pid,
                "limit": 1000,
                "page": 1,
                "deviceVersion": DEVICE_VERSION,
                "versionNumber": APP_VERSION,
                "appLanguage": LANGUAGE_TYPE,
                "modelClassId": model_class_id,
            },
        )
        effects: dict[str, str] = {}
        if not isinstance(data, dict):
            return effects
        for item in data.get("list") or []:
            if not isinstance(item, dict):
                continue
            _add_effect(effects, item.get("modelName"), item.get("modelOrder"))
        return effects

    async def async_get_rhythm_effects(
        self, device_pid: str = DEFAULT_PID
    ) -> dict[str, str]:
        """Fetch on-device microphone rhythm presets mapped as {name: HEX_COMMAND}."""
        data = await self._post(
            ENDPOINT_GET_RHYTHM_MODEL,
            json_body={
                "devicePid": device_pid,
                "deviceVersion": DEVICE_VERSION,
                "versionNumber": APP_VERSION,
                "appLanguage": LANGUAGE_TYPE,
            },
        )
        effects: dict[str, str] = {}
        if not isinstance(data, dict):
            return effects
        for item in data.get("deviceList") or []:
            if not isinstance(item, dict):
                continue
            _add_effect(effects, item.get("rhythmName"), item.get("rhythmOrder"))
        return effects

    async def async_get_effect_catalog(
        self, device_pid: str = DEFAULT_PID
    ) -> EffectCatalog:
        """Fetch categorized, sorted scene and on-device rhythm presets."""
        by_category: dict[str, dict[str, str]] = {}

        try:
            classes = await self.async_get_model_classes(device_pid)
        except DayBetterError as err:
            _LOGGER.debug("Failed to load model classes for %s: %s", device_pid, err)
            classes = []

        for model_class in classes:
            class_id = model_class.get("modelClassId")
            if class_id is None:
                continue
            try:
                numeric_id = int(class_id)
                edition = await self.async_get_edition_scenes(numeric_id, device_pid)
            except (DayBetterError, ValueError) as err:
                _LOGGER.debug(
                    "Failed to load edition scenes for class %s: %s", class_id, err
                )
                continue
            if not edition:
                continue
            cat_name = str(
                model_class.get("modelClassName")
                or _MODEL_CLASS_NAMES.get(numeric_id)
                or f"Scene {numeric_id}"
            ).strip()
            bucket = by_category.setdefault(cat_name, {})
            for name, order in edition.items():
                bucket.setdefault(name, order)

        try:
            classics = await self.async_get_classic_scenes(device_pid)
            if classics:
                bucket = by_category.setdefault("Classic", {})
                for name, order in classics.items():
                    bucket.setdefault(name, order)
        except DayBetterError as err:
            _LOGGER.debug("Failed to load classic scenes for %s: %s", device_pid, err)

        try:
            rhythms = await self.async_get_rhythm_effects(device_pid)
            if rhythms:
                bucket = by_category.setdefault("Rhythm", {})
                for name, order in rhythms.items():
                    bucket.setdefault(name, order)
        except DayBetterError as err:
            _LOGGER.debug("Failed to load rhythm effects for %s: %s", device_pid, err)

        catalog = EffectCatalog.from_categories(by_category)
        _LOGGER.debug(
            "Loaded %d effects across %d categories for PID %s (%s)",
            len(catalog.flat),
            len(catalog.by_category),
            device_pid,
            catalog.categories,
        )
        return catalog

    async def async_get_all_effects(
        self, device_pid: str = DEFAULT_PID
    ) -> dict[str, str]:
        """Return flat category-prefixed {name: HEX_COMMAND} map for a device PID."""
        catalog = await self.async_get_effect_catalog(device_pid)
        return catalog.flat


_HEX_CHARS = frozenset("0123456789ABCDEF")


def _add_effect(target: dict[str, str], name: Any, order: Any) -> None:
    if not name or not order:
        return
    clean_name = str(name).strip()
    clean_order = str(order).strip().replace(" ", "").upper()
    if (
        not clean_name
        or not clean_order
        or len(clean_order) % 2 != 0
        or any(ch not in _HEX_CHARS for ch in clean_order)
    ):
        return
    target.setdefault(clean_name, clean_order)
