from __future__ import annotations

import ipaddress
from pathlib import Path
import re

from homeassistant.components.frontend import add_extra_js_url
try:
    from homeassistant.components.http import StaticPathConfig
except ImportError:  # Home Assistant < 2024.7
    StaticPathConfig = None  # type: ignore[misc, assignment]
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import TendaMW6Api, extract_login_account
from .coordinator import TendaMW6Coordinator

DOMAIN = "tenda_mw6"
PLATFORMS: tuple[Platform, ...] = (
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
)
CONF_LOGIN_ACCOUNT = "login_account"
CONF_DEVICE_ALIASES = "device_aliases"
LEGACY_LOGIN_PAYLOAD = "login_payload_hex"
FRONTEND_URL = f"/{DOMAIN}/tenda-mw6-card.js"
FRONTEND_PATH = Path(__file__).with_name("tenda-mw6-card.js")

_MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$", re.IGNORECASE)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the bundled Lovelace card exactly once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("frontend_registered"):
        return

    if StaticPathConfig is not None and hasattr(
        hass.http, "async_register_static_paths"
    ):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL, str(FRONTEND_PATH), False)]
        )
    else:
        hass.http.register_static_path(FRONTEND_URL, str(FRONTEND_PATH), False)

    add_extra_js_url(hass, FRONTEND_URL)
    domain_data["frontend_registered"] = True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register frontend assets independently of router availability."""
    await _async_register_frontend(hass)
    return True


def _normalize_device_selector(selector: str, line_number: int) -> str:
    """Normalize one exact IP or MAC selector."""
    try:
        return str(ipaddress.ip_address(selector))
    except ValueError:
        normalized = selector.lower().replace("-", ":")
        if not _MAC_RE.fullmatch(normalized):
            raise ValueError(f"Invalid IP or MAC on line {line_number}") from None
        return normalized


def parse_device_aliases(raw: str) -> dict[str, str]:
    """Parse newline-separated IP | MAC = alias entries.

    An empty alias is intentional and forces the client IP to be displayed.
    """
    aliases: dict[str, str] = {}
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        selectors_raw, separator, alias = line.partition("=")
        selectors = [
            selector.strip()
            for selector in selectors_raw.split("|")
            if selector.strip()
        ]
        if not separator or not selectors:
            raise ValueError(f"Invalid alias mapping on line {line_number}")

        alias = alias.strip()
        for selector in selectors:
            aliases[_normalize_device_selector(selector, line_number)] = alias

    return aliases


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
    await _async_register_frontend(hass)
    api = TendaMW6Api(
        host=entry.data["host"],
        port=int(entry.data.get("port", 9000)),
        login_account=str(entry.data[CONF_LOGIN_ACCOUNT]),
    )
    aliases = parse_device_aliases(str(entry.options.get(CONF_DEVICE_ALIASES, "")))
    coordinator = TendaMW6Coordinator(hass, api, device_aliases=aliases)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after its alias options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Tenda MW6 config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
