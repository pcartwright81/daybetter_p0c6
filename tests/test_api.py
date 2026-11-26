from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from custom_components.daybetter_p0c6.api import (
    DayBetterApiClient,
    DayBetterAuthError,
    DayBetterError,
)
from custom_components.daybetter_p0c6.const import (
    API_BASE_URL,
    ENDPOINT_CONTROL_DEVICE,
    ENDPOINT_GET_APP_USER,
    ENDPOINT_GET_DEVICE,
    ENDPOINT_GET_MODEL_CLASS,
    ENDPOINT_GET_MODEL_CLASSICS,
    ENDPOINT_GET_MODEL_EDITION,
    ENDPOINT_GET_RHYTHM_MODEL,
    ENDPOINT_LOGIN_EMAIL,
    ENDPOINT_REQUEST_OTP,
)


@dataclass
class _FakeResponse:
    payload: dict[str, Any]
    status: int = 200

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self, *, content_type: str | None = None) -> dict[str, Any]:
        return self.payload


class _FakeSession:
    def __init__(
        self, responses: dict[str, _FakeResponse | list[_FakeResponse]]
    ) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((url, kwargs))
        endpoint = url.removeprefix(API_BASE_URL)
        entry = self._responses[endpoint]
        if isinstance(entry, list):
            return entry.pop(0)
        return entry


async def test_email_otp_and_login_flow() -> None:
    session = _FakeSession(
        {
            ENDPOINT_REQUEST_OTP: _FakeResponse(
                {"code": 1, "message": "success", "data": None}
            ),
            ENDPOINT_LOGIN_EMAIL: _FakeResponse(
                {
                    "code": 1,
                    "message": "success",
                    "data": {
                        "userToken": "tok_abc",
                        "userName": "user@example.com",
                        "userGroup": 1000001,
                    },
                }
            ),
        }
    )
    client = DayBetterApiClient(session)  # type: ignore[arg-type]

    await client.async_request_email_otp("user@example.com")
    user = await client.async_login_email("user@example.com", "123456")

    assert user.token == "tok_abc"
    assert user.user_group == 1000001
    assert user.email == "user@example.com"
    assert client.token == "tok_abc"

    otp_url, otp_kwargs = session.calls[0]
    assert otp_url.endswith(ENDPOINT_REQUEST_OTP)
    assert otp_kwargs["json"] == {"accountType": 0, "userEmail": "user@example.com"}
    assert "Authorization" not in otp_kwargs["headers"]

    login_url, login_kwargs = session.calls[1]
    assert login_url.endswith(ENDPOINT_LOGIN_EMAIL)
    assert login_kwargs["json"] == {"code": "123456", "account": "user@example.com"}


async def test_get_app_user_uses_form_urlencoded_empty_body() -> None:
    session = _FakeSession(
        {
            ENDPOINT_GET_APP_USER: _FakeResponse(
                {
                    "code": 1,
                    "message": "success",
                    "data": {
                        "userName": "testuser",
                        "userMailbox": "user@example.com",
                        "userGroup": 1000001,
                    },
                }
            )
        }
    )
    client = DayBetterApiClient(session, token="tok_live")  # type: ignore[arg-type]

    user = await client.async_get_app_user()

    assert user.user_group == 1000001
    assert user.email == "user@example.com"
    _, kwargs = session.calls[0]
    assert kwargs["headers"]["Authorization"] == "tok_live"
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert kwargs["data"] == ""
    assert "json" not in kwargs


async def test_get_devices_and_set_power() -> None:
    session = _FakeSession(
        {
            ENDPOINT_GET_DEVICE: _FakeResponse(
                {
                    "code": 1,
                    "message": "success",
                    "data": [
                        {
                            "deviceId": 100001,
                            "deviceName": "DEVTOPIC0001",
                            "deviceGroupName": "Bedroom Lamp",
                            "deviceState": 1,
                            "deviceSwitchStatus": 1,
                            "deviceMac": "AA:BB:CC:DD:EE:01",
                            "deviceWlanMac": "AA:BB:CC:DD:EE:02",
                            "deviceMoldPid": "P0C6",
                        },
                        {
                            "deviceId": 100002,
                            "deviceName": "DEVTOPIC0002",
                            "deviceGroupName": "Desk Lamp",
                            "deviceState": 0,
                            "deviceSwitchStatus": 0,
                            "deviceMac": "AA:BB:CC:DD:EE:03",
                            "deviceWlanMac": "AA:BB:CC:DD:EE:04",
                            "deviceMoldPid": "P0C6",
                        },
                    ],
                }
            ),
            ENDPOINT_CONTROL_DEVICE: _FakeResponse(
                {"code": 1, "message": "success", "data": None}
            ),
        }
    )
    client = DayBetterApiClient(session, token="tok_live")  # type: ignore[arg-type]

    devices = await client.async_get_devices(1000001)
    assert len(devices) == 2
    assert devices[0].device_id == 100001
    assert devices[0].topic == "DEVTOPIC0001"
    assert devices[0].name == "Bedroom Lamp"
    assert devices[0].online is True
    assert devices[0].is_on is True
    assert devices[0].wlan_mac == "AA:BB:CC:DD:EE:02"
    assert devices[1].online is False
    assert devices[1].is_on is False

    await client.async_set_power(100002, True)
    _, kwargs = session.calls[1]
    assert kwargs["json"] == {"deviceSwitchStatus": 1, "deviceId": 100002}


async def test_get_all_effects_aggregates_classics_editions_and_rhythms() -> None:
    session = _FakeSession(
        {
            ENDPOINT_GET_MODEL_CLASSICS: _FakeResponse(
                {
                    "code": 1,
                    "message": "success",
                    "data": {
                        "list": [
                            {
                                "modelClassicsAppQoList": [
                                    {
                                        "modelName": "Warm Fade",
                                        "modelOrder": "a009082a070200",
                                    }
                                ]
                            }
                        ]
                    },
                }
            ),
            ENDPOINT_GET_MODEL_CLASS: _FakeResponse(
                {
                    "code": 1,
                    "message": "success",
                    "data": [{"modelClassId": 6}, {"modelClassId": 7}],
                }
            ),
            ENDPOINT_GET_MODEL_EDITION: [
                _FakeResponse(
                    {
                        "code": 1,
                        "message": "success",
                        "data": {
                            "list": [
                                {
                                    "modelName": "Duskglow",
                                    "modelOrder": '{"NAME":"test","ACTION":5}',
                                },
                                {
                                    "modelName": "Christmas",
                                    "modelOrder": "a009042270FF",
                                },
                            ]
                        },
                    }
                ),
                _FakeResponse(
                    {
                        "code": 1,
                        "message": "success",
                        "data": {
                            "list": [
                                {
                                    "modelName": "Pleasure",
                                    "modelOrder": "a0090428F0F8",
                                }
                            ]
                        },
                    }
                ),
            ],
            ENDPOINT_GET_RHYTHM_MODEL: _FakeResponse(
                {
                    "code": 1,
                    "message": "success",
                    "data": {
                        "deviceList": [
                            {"rhythmName": "Spectrum", "rhythmOrder": "a00904311122"}
                        ],
                        "phoneList": [
                            {"rhythmName": "Pulse", "rhythmOrder": "a00904323344"}
                        ],
                    },
                }
            ),
        }
    )
    client = DayBetterApiClient(session, token="tok_live")  # type: ignore[arg-type]

    effects = await client.async_get_all_effects("P0C6")

    assert effects == {
        "Classic: Warm Fade": "A009082A070200",
        "Festival: Christmas": "A009042270FF",
        "Moods: Pleasure": "A0090428F0F8",
        "Rhythm: Spectrum": "A00904311122",
    }
    assert list(effects) == [
        "Classic: Warm Fade",
        "Festival: Christmas",
        "Moods: Pleasure",
        "Rhythm: Spectrum",
    ]


async def test_auth_errors_raise_daybetter_auth_error() -> None:
    session = _FakeSession(
        {
            ENDPOINT_GET_APP_USER: _FakeResponse(
                {"code": 401, "message": "token expired", "data": None},
                status=401,
            ),
            ENDPOINT_GET_DEVICE: _FakeResponse(
                {"code": 0, "message": "something failed", "data": None}
            ),
        }
    )
    client = DayBetterApiClient(session, token="expired")  # type: ignore[arg-type]

    with pytest.raises(DayBetterAuthError):
        await client.async_get_app_user()

    with pytest.raises(DayBetterError):
        await client.async_get_devices(1000001)
