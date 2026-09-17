from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorEntity

from .api import TendaMW6Client
from .coordinator import TendaMW6Coordinator
from . import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for each client known at first refresh."""
    coordinator: TendaMW6Coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    for client in coordinator.data:
        if not client.mac:
            continue
        entities.extend(
            (
                TendaMW6ClientSignalSensor(coordinator, entry, client.mac),
                TendaMW6ClientIpSensor(coordinator, entry, client.mac),
                TendaMW6ClientNodeSensor(coordinator, entry, client.mac),
            )
        )

    async_add_entities(entities)


class TendaMW6ClientSensorBase(CoordinatorEntity[TendaMW6Coordinator], SensorEntity):
    """Base sensor for one MW6 client."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._mac = mac.lower()

    @property
    def _client(self) -> TendaMW6Client | None:
        for client in self.coordinator.data:
            if client.mac.lower() == self._mac:
                return client
        return None

    @property
    def available(self) -> bool:
        return super().available and self._client is not None

    @property
    def device_info(self) -> DeviceInfo:
        client = self._client
        display_name = (
            client.name
            if client is not None and client.name
            else (client.ip if client is not None and client.ip else self._mac)
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}:{self._mac}")},
            name=display_name,
            manufacturer="Tenda",
            model="Nova MW6 client",
        )


class TendaMW6ClientSignalSensor(TendaMW6ClientSensorBase):
    """Signal sensor for one MW6 client."""

    _attr_icon = "mdi:wifi"
    _attr_native_unit_of_measurement = "dBm"

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator, entry, mac)
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_signal"
        self._attr_name = "Signal"

    @property
    def native_value(self) -> int | None:
        client = self._client
        return client.signal if client is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        client = self._client
        if client is None:
            return {"mac": self._mac}

        attrs: dict[str, Any] = {
            "ip": client.ip,
            "mac": client.mac,
            "name": client.name,
            "node_sn": client.node_sn,
            "signal": client.signal,
            "access": client.access,
            "condition_time": client.condition_time,
        }

        # These three values are intentionally exposed only as raw diagnostics.
        # Live tests on MW6 firmware showed that they remain zero even for an
        # active client, so they must not be treated as authoritative status/rate.
        attrs["raw_online"] = client.raw_online
        attrs["raw_uprate"] = client.raw_uprate
        attrs["raw_downrate"] = client.raw_downrate
        return attrs


class TendaMW6ClientIpSensor(TendaMW6ClientSensorBase):
    """Current IPv4 address reported for one MW6 client."""

    _attr_icon = "mdi:ip-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator, entry, mac)
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_ip"
        self._attr_name = "IP address"

    @property
    def native_value(self) -> str | None:
        client = self._client
        return client.ip or None if client is not None else None


class TendaMW6ClientNodeSensor(TendaMW6ClientSensorBase):
    """Mesh node identifier currently associated with one MW6 client."""

    _attr_icon = "mdi:access-point-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator, entry, mac)
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_node"
        self._attr_name = "Mesh node"

    @property
    def native_value(self) -> str | None:
        client = self._client
        return client.node_sn or None if client is not None else None
