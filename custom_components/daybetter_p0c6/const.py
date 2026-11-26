from __future__ import annotations

from datetime import timedelta

DOMAIN = "daybetter_p0c6"

API_BASE_URL = "https://a.dbiot.org"
WS_URL_TEMPLATE = "wss://a.dbiot.org/iot/{token}"

APP_VERSION = "1.9.5"
DEVICE_VERSION = "9.9.9"
LANGUAGE_TYPE = "EN"
SYSTEM_MODEL = "Android"
USER_AGENT = "okhttp/4.12.0"

DEFAULT_PID = "P0C6"
SUPPORTED_PIDS = frozenset({DEFAULT_PID})

CONF_TOKEN = "token"
CONF_USER_GROUP = "user_group"
CONF_EMAIL = "email"
CONF_OTP_CODE = "otp_code"

SCAN_INTERVAL = timedelta(seconds=60)
WS_HEARTBEAT_INTERVAL = 20
WS_RECONNECT_MIN_DELAY = 5
WS_RECONNECT_MAX_DELAY = 120

CMD_POWER_ON = "A0110401B121"
CMD_POWER_OFF = "A011040070E1"
CMD_QUERY_STATE = "A0100401E0E1"

RGB_FRAME_HEADER = bytes.fromhex("A0041A")
RGB_FRAME_SEGMENTS = bytes(range(1, 21))

SERVICE_SEND_RAW_COMMAND = "send_raw_command"
ATTR_HEX_DATA = "hex_data"

ENDPOINT_REQUEST_OTP = "/public/app/captcha/emailNewCode"
ENDPOINT_LOGIN_EMAIL = "/public/app/user/login/newEmail"
ENDPOINT_GET_APP_USER = "/user/app/getAppUser"
ENDPOINT_GET_DEVICE = "/device/app/getDevice"
ENDPOINT_CONTROL_DEVICE = "/device/app/controlDeviceInList"
ENDPOINT_GET_MODEL_CLASS = "/model/multi/app/getModelClass"
ENDPOINT_GET_MODEL_CLASSICS = "/model/multi/app/getModelClassicsNewPage"
ENDPOINT_GET_MODEL_EDITION = "/model/multi/app/getModelNewEditionPage"
ENDPOINT_GET_RHYTHM_MODEL = "/model/multi/app/getRhythmModel"
