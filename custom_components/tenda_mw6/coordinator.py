from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TendaMW6Api, TendaMW6Client, TendaMW6Error


class TendaMW6Coordinator(DataUpdateCoordinator[list[TendaMW6Client]]):
    """Poll the MW6 local TCP/9000 API."""

    def __init__(self, hass: HomeAssistant, api: TendaMW6Api) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="Tenda MW6 clients",
            update_interval=timedelta(seconds=10),
        )
        self.api = api

    async def _async_update_data(self) -> list[TendaMW6Client]:
        try:
            return await self.hass.async_add_executor_job(self.api.get_clients)
        except (OSError, TendaMW6Error) as exc:
            raise UpdateFailed(f"Unable to read Tenda MW6 clients: {exc}") from exc
