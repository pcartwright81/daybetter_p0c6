from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .api import (
    DayBetterApiClient,
    DayBetterAuthError,
    DayBetterConnectionError,
    DayBetterError,
    DayBetterUser,
)
from .const import CONF_EMAIL, CONF_OTP_CODE, CONF_TOKEN, CONF_USER_GROUP, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_TOKEN_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})
STEP_EMAIL_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str})
STEP_OTP_SCHEMA = vol.Schema({vol.Required(CONF_OTP_CODE): str})


class DayBetterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DayBetter P0C6."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose between Email + OTP login or token paste."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["email_otp", "token"],
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the token expires."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose how to re-authenticate."""
        return self.async_show_menu(
            step_id="reauth_confirm",
            menu_options=["email_otp", "token"],
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure or re-authenticate by pasting a userToken."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            session = async_get_clientsession(self.hass)
            client = DayBetterApiClient(session, token=token)
            try:
                user = await client.async_get_app_user()
            except DayBetterAuthError:
                errors["base"] = "invalid_auth"
            except DayBetterConnectionError:
                errors["base"] = "cannot_connect"
            except DayBetterError:
                _LOGGER.exception("Unexpected API error validating token")
                errors["base"] = "unknown"
            else:
                return await self._async_finish_auth(user)

        return self.async_show_form(
            step_id="token",
            data_schema=STEP_TOKEN_SCHEMA,
            errors=errors,
        )

    async def async_step_email_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request a 6-digit OTP code for the user's DayBetter email."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            session = async_get_clientsession(self.hass)
            client = DayBetterApiClient(session)
            try:
                await client.async_request_email_otp(email)
            except DayBetterConnectionError:
                errors["base"] = "cannot_connect"
            except DayBetterError:
                _LOGGER.exception("Failed to request DayBetter OTP")
                errors["base"] = "otp_request_failed"
            else:
                self._email = email
                return await self.async_step_verify_otp()

        return self.async_show_form(
            step_id="email_otp",
            data_schema=STEP_EMAIL_SCHEMA,
            errors=errors,
        )

    async def async_step_verify_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify the 6-digit OTP code and obtain a session token."""
        errors: dict[str, str] = {}
        if user_input is not None and self._email:
            otp_code = user_input[CONF_OTP_CODE].strip()
            session = async_get_clientsession(self.hass)
            client = DayBetterApiClient(session)
            try:
                user = await client.async_login_email(self._email, otp_code)
            except DayBetterAuthError:
                errors["base"] = "invalid_auth"
            except DayBetterConnectionError:
                errors["base"] = "cannot_connect"
            except DayBetterError:
                _LOGGER.exception("Failed to verify DayBetter OTP")
                errors["base"] = "invalid_auth"
            else:
                return await self._async_finish_auth(user)

        return self.async_show_form(
            step_id="verify_otp",
            data_schema=STEP_OTP_SCHEMA,
            description_placeholders={"email": self._email or ""},
            errors=errors,
        )

    async def _async_finish_auth(self, user: DayBetterUser) -> ConfigFlowResult:
        entry_data = {
            CONF_TOKEN: user.token,
            CONF_USER_GROUP: user.user_group,
            CONF_EMAIL: user.email,
        }
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates=entry_data,
            )

        await self.async_set_unique_id(str(user.user_group))
        self._abort_if_unique_id_configured()

        title = user.email or user.user_name or f"DayBetter ({user.user_group})"
        return self.async_create_entry(title=title, data=entry_data)
