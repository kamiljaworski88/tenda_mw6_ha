from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import TendaMW6Api
from .coordinator import TendaMW6Coordinator

DOMAIN = "tenda_mw6"
PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tenda MW6 from a config entry."""
    api = TendaMW6Api(
        host=entry.data["host"],
        port=int(entry.data.get("port", 9000)),
        login_payload=bytes.fromhex(entry.data["login_payload_hex"]),
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
