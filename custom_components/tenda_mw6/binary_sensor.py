from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .api import TendaMW6Client
from .coordinator import TendaMW6Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add an online-state entity for each client discovered by the coordinator."""
    coordinator: TendaMW6Coordinator = hass.data[DOMAIN][entry.entry_id]
    known_macs: set[str] = set()

    def add_new_clients() -> None:
        entities: list[BinarySensorEntity] = []
        for client in coordinator.data or []:
            mac = client.mac.strip().lower()
            if not mac or mac in known_macs:
                continue
            known_macs.add(mac)
            entities.append(TendaMW6ClientOnlineBinarySensor(coordinator, entry, mac))

        if entities:
            async_add_entities(entities)

    add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(add_new_clients))


class TendaMW6ClientOnlineBinarySensor(
    CoordinatorEntity[TendaMW6Coordinator], BinarySensorEntity
):
    """Reported client online state, withheld when the complete inventory is stale."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._mac = mac.lower()
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_online"

    @property
    def _client(self) -> TendaMW6Client | None:
        for client in self.coordinator.data or []:
            if client.mac.lower() == self._mac:
                return client
        return None

    @property
    def available(self) -> bool:
        """Avoid claiming a client is offline when all MW6 inventory is stale."""
        return (
            super().available
            and self._client is not None
            and not self.coordinator.inventory_summary.all_reported_offline
        )

    @property
    def is_on(self) -> bool | None:
        client = self._client
        return bool(client.raw_online) if client is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        client = self._client
        summary = self.coordinator.inventory_summary
        return {
            "tenda_mw6_client": True,
            "tenda_mw6_metric": "online",
            "config_entry_id": self._entry.entry_id,
            "client_mac": client.mac.lower() if client is not None else self._mac,
            "client_ip": client.ip or None if client is not None else None,
            "client_name": (
                self.coordinator.client_display_name(client)
                if client is not None
                else self._mac
            ),
            "ip": client.ip if client is not None else None,
            "mac": client.mac if client is not None else self._mac,
            "node_sn": client.node_sn if client is not None else None,
            "raw_online": client.raw_online if client is not None else None,
            "inventory_all_reported_offline": summary.all_reported_offline,
        }

    @property
    def device_info(self) -> DeviceInfo:
        client = self._client
        display_name = (
            self.coordinator.client_display_name(client)
            if client is not None
            else self._mac
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}:{self._mac}")},
            name=display_name,
            manufacturer="Tenda",
            model="Nova MW6 client",
        )
