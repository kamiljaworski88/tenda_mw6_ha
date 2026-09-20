from __future__ import annotations

import ipaddress
import socket
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from . import (
    CONF_DEVICE_ALIASES,
    DOMAIN,
    parse_device_aliases,
)
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
        """Return the flow used to edit device aliases."""
        return TendaMW6OptionsFlow()

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
                vol.Required(CONF_HOST, default="192.168.0.1"): str,
                vol.Required(CONF_PORT, default=9000): vol.Coerce(int),
                vol.Required(CONF_LOGIN_ACCOUNT): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


def _client_sort_key(client: Any) -> tuple[int, int, int, str]:
    """Sort clients by IP, with malformed or missing addresses last."""
    try:
        address = ipaddress.ip_address(client.ip.strip())
        return (0, address.version, int(address), client.mac.lower())
    except ValueError:
        return (1, 0, 0, f"{client.ip}|{client.mac}".lower())


def _render_current_device_map(
    hass: HomeAssistant,
    entry: ConfigEntry,
    saved_raw: str,
) -> str:
    """Render every currently known client as IP | MAC = name."""
    try:
        saved_aliases = parse_device_aliases(saved_raw)
    except ValueError:
        return saved_raw

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    clients = list(coordinator.data or []) if coordinator is not None else []
    if not clients:
        return saved_raw

    lines = [
        "# IP | MAC = Nazwa",
        "# Pusta nazwa po znaku = wymusza wyświetlanie adresu IP.",
    ]
    used_keys: set[str] = set()

    for client in sorted(clients, key=_client_sort_key):
        ip = client.ip.strip()
        mac = client.mac.strip().lower().replace("-", ":")
        keys = [key for key in (ip, mac) if key]

        alias_was_saved = False
        alias = ""
        for key in keys:
            if key in saved_aliases:
                alias = saved_aliases[key]
                alias_was_saved = True
                break

        if not alias_was_saved:
            alias = client.name.strip()

        for key in keys:
            if key in saved_aliases:
                used_keys.add(key)

        selectors = " | ".join(keys)
        if selectors:
            lines.append(f"{selectors} = {alias}")

    for key, alias in saved_aliases.items():
        if key not in used_keys:
            lines.append(f"{key} = {alias}")

    return "\n".join(lines)


class TendaMW6OptionsFlow(config_entries.OptionsFlow):
    """Manage user-defined names for known clients."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the live IP/MAC/name map."""
        errors: dict[str, str] = {}
        submitted_raw: str | None = None

        if user_input is not None:
            submitted_raw = str(user_input.get(CONF_DEVICE_ALIASES, ""))
            try:
                parse_device_aliases(submitted_raw)
            except ValueError:
                errors["base"] = "invalid_aliases"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_DEVICE_ALIASES: submitted_raw},
                )

        entry = self.hass.config_entries.async_get_entry(self.handler)
        saved_raw = (
            str(entry.options.get(CONF_DEVICE_ALIASES, "")) if entry is not None else ""
        )
        current_map = (
            submitted_raw
            if submitted_raw is not None
            else (
                _render_current_device_map(self.hass, entry, saved_raw)
                if entry is not None
                else saved_raw
            )
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEVICE_ALIASES,
                    default=current_map,
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                )
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
