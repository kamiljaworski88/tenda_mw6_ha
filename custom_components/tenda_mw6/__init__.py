from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import TendaMW6Api, extract_login_account
from .coordinator import TendaMW6Coordinator

DOMAIN = "tenda_mw6"
PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)
CONF_LOGIN_ACCOUNT = "login_account"
LEGACY_LOGIN_PAYLOAD = "login_payload_hex"


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate v1 entries from a raw LoginMsg payload to the account value."""
    if entry.version >= 2:
        return True

    if entry.version == 1:
        data = dict(entry.data)
        legacy_hex = data.pop(LEGACY_LOGIN_PAYLOAD, None)
        if legacy_hex is None:
            return False
        try:
            account = extract_login_account(bytes.fromhex(str(legacy_hex).replace(" ", "")))
        except (ValueError, UnicodeError):
            return False
        data[CONF_LOGIN_ACCOUNT] = account
        hass.config_entries.async_update_entry(entry, data=data, version=2)
        return True

    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tenda MW6 from a config entry."""
    api = TendaMW6Api(
        host=entry.data["host"],
        port=int(entry.data.get("port", 9000)),
        login_account=str(entry.data[CONF_LOGIN_ACCOUNT]),
    )
    coordinator = TendaMW6Coordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Tenda MW6 config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
