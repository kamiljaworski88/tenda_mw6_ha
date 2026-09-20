from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    TendaMW6Api,
    TendaMW6Client,
    TendaMW6Error,
    TendaMW6InventorySummary,
    TendaMW6TransferReadiness,
    summarize_inventory,
    summarize_transfer_readiness,
)


class TendaMW6Coordinator(DataUpdateCoordinator[list[TendaMW6Client]]):
    """Poll the MW6 local TCP/9000 API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TendaMW6Api,
        device_aliases: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="Tenda MW6 clients",
            update_interval=timedelta(seconds=10),
        )
        self.api = api
        self.device_aliases = device_aliases or {}
        self._last_reported_online_at: datetime | None = None

    async def _async_update_data(self) -> list[TendaMW6Client]:
        try:
            clients = await self.hass.async_add_executor_job(self.api.get_clients)
            if summarize_inventory(clients).reported_online:
                self._last_reported_online_at = dt_util.utcnow()
            return clients
        except (OSError, TendaMW6Error) as exc:
            raise UpdateFailed(f"Unable to read Tenda MW6 clients: {exc}") from exc

    def client_display_name(self, client: TendaMW6Client) -> str:
        """Return a configured alias or the best name reported by the MW6."""
        ip_key = client.ip.strip().lower()
        mac_key = client.mac.strip().lower().replace("-", ":")

        for key in (ip_key, mac_key):
            if key in self.device_aliases:
                # A deliberately empty alias means "show the current IP".
                return self.device_aliases[key] or ip_key or mac_key

        return client.name.strip() or ip_key or mac_key

    @property
    def inventory_summary(self) -> TendaMW6InventorySummary:
        """Return the current HostList online-state summary."""
        return summarize_inventory(self.data or [])

    @property
    def transfer_readiness(self) -> TendaMW6TransferReadiness:
        """Return whether the current HostList can drive local transfer counters."""
        return summarize_transfer_readiness(self.data or [])

    @property
    def last_reported_online_at(self) -> datetime | None:
        """Return when a successful poll last contained any reported-online client.

        This is local Home Assistant observation time, not the firmware's
        last_seen value, which is not exposed through the confirmed API.
        """
        return self._last_reported_online_at
