from __future__ import annotations

import socket

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from . import DOMAIN
from .api import LOGIN_ACCOUNT_RE, TendaMW6Api, TendaMW6AuthError, TendaMW6Error

CONF_LOGIN_ACCOUNT = "login_account"


async def _validate_input(hass: HomeAssistant, data: dict) -> None:
    login_account = str(data[CONF_LOGIN_ACCOUNT]).strip()
    if not LOGIN_ACCOUNT_RE.fullmatch(login_account):
        raise ValueError("invalid_login_account")

    api = TendaMW6Api(
        host=str(data[CONF_HOST]),
        port=int(data[CONF_PORT]),
        login_account=login_account,
    )
    await hass.async_add_executor_job(api.validate)


class TendaMW6ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tenda MW6."""

    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_input(self.hass, user_input)
            except TendaMW6AuthError:
                errors["base"] = "invalid_auth"
            except (TendaMW6Error, socket.timeout, OSError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_account"
            else:
                host = str(user_input[CONF_HOST]).strip()
                account = str(user_input[CONF_LOGIN_ACCOUNT]).strip()
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Tenda MW6 ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: int(user_input[CONF_PORT]),
                        CONF_LOGIN_ACCOUNT: account,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="192.168.5.1"): str,
                vol.Required(CONF_PORT, default=9000): vol.Coerce(int),
                vol.Required(CONF_LOGIN_ACCOUNT): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
