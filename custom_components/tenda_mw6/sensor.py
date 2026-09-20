from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import DOMAIN
from .api import TendaMW6Client, estimate_transfer_bytes
from .coordinator import TendaMW6Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors and add newly discovered MW6 clients dynamically."""
    coordinator: TendaMW6Coordinator = hass.data[DOMAIN][entry.entry_id]
    known_macs: set[str] = set()
    async_add_entities(
        [
            TendaMW6InventoryHealthSensor(coordinator, entry),
            TendaMW6TransferHealthSensor(coordinator, entry),
            TendaMW6AggregateRateSensor(coordinator, entry, "upload"),
            TendaMW6AggregateRateSensor(coordinator, entry, "download"),
            TendaMW6AggregateTransferSensor(coordinator, entry, "upload", "total"),
            TendaMW6AggregateTransferSensor(coordinator, entry, "download", "total"),
            TendaMW6AggregateTransferSensor(coordinator, entry, "upload", "day"),
            TendaMW6AggregateTransferSensor(coordinator, entry, "download", "day"),
            TendaMW6AggregateTransferSensor(coordinator, entry, "upload", "month"),
            TendaMW6AggregateTransferSensor(coordinator, entry, "download", "month"),
        ]
    )

    def add_new_clients() -> None:
        entities: list[SensorEntity] = []
        for client in coordinator.data or []:
            mac = client.mac.strip().lower()
            if not mac or mac in known_macs:
                continue
            known_macs.add(mac)
            entities.extend(
                (
                    TendaMW6ClientSignalSensor(coordinator, entry, mac),
                    TendaMW6ClientIpSensor(coordinator, entry, mac),
                    TendaMW6ClientAccessSensor(coordinator, entry, mac),
                    TendaMW6ClientNodeSensor(coordinator, entry, mac),
                    TendaMW6ClientRateSensor(coordinator, entry, mac, "upload"),
                    TendaMW6ClientRateSensor(coordinator, entry, mac, "download"),
                    TendaMW6ClientTransferSensor(coordinator, entry, mac, "upload", "total"),
                    TendaMW6ClientTransferSensor(coordinator, entry, mac, "download", "total"),
                    TendaMW6ClientTransferSensor(coordinator, entry, mac, "upload", "day"),
                    TendaMW6ClientTransferSensor(coordinator, entry, mac, "download", "day"),
                    TendaMW6ClientTransferSensor(coordinator, entry, mac, "upload", "month"),
                    TendaMW6ClientTransferSensor(coordinator, entry, mac, "download", "month"),
                )
            )

        if entities:
            async_add_entities(entities)

    add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(add_new_clients))


class TendaMW6InventoryHealthSensor(CoordinatorEntity[TendaMW6Coordinator], SensorEntity):
    """Expose whether the HostList has any client reported online."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:database-alert-outline"
    _attr_name = "Inventory health"

    def __init__(self, coordinator: TendaMW6Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_inventory_health"

    @property
    def native_value(self) -> str:
        summary = self.coordinator.inventory_summary
        if summary.total_clients == 0:
            return "no_clients"
        return "all_reported_offline" if summary.all_reported_offline else "reporting"

    @property
    def extra_state_attributes(self) -> dict[str, int | bool | str | None]:
        summary = self.coordinator.inventory_summary
        last_reported_online_at = self.coordinator.last_reported_online_at
        return {
            "total_clients": summary.total_clients,
            "reported_online": summary.reported_online,
            "reported_offline": summary.reported_offline,
            "unknown_online_state": summary.unknown_online_state,
            "all_reported_offline": summary.all_reported_offline,
            "last_reported_online_at": (
                last_reported_online_at.isoformat() if last_reported_online_at else None
            ),
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Tenda MW6",
            manufacturer="Tenda",
            model="Nova MW6",
        )


class TendaMW6TransferHealthSensor(CoordinatorEntity[TendaMW6Coordinator], SensorEntity):
    """Explain whether current MW6 samples can advance local transfer counters."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-timeline-variant"
    _attr_name = "Transfer counting health"

    def __init__(self, coordinator: TendaMW6Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_transfer_counting_health"

    @property
    def native_value(self) -> str:
        readiness = self.coordinator.transfer_readiness
        if readiness.inventory_all_reported_offline:
            return "inventory_stale"
        if readiness.eligible_clients == 0:
            return "waiting_for_online_clients"
        if readiness.clients_with_rate == 0:
            return "waiting_for_rate_observation"
        return "rate_observed"

    @property
    def extra_state_attributes(self) -> dict[str, int | bool]:
        readiness = self.coordinator.transfer_readiness
        return {
            "eligible_clients": readiness.eligible_clients,
            "clients_with_rate": readiness.clients_with_rate,
            "clients_with_upload_rate": readiness.clients_with_upload_rate,
            "clients_with_download_rate": readiness.clients_with_download_rate,
            "inventory_all_reported_offline": readiness.inventory_all_reported_offline,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Tenda MW6",
            manufacturer="Tenda",
            model="Nova MW6",
        )


class TendaMW6AggregateSensorBase(CoordinatorEntity[TendaMW6Coordinator], SensorEntity):
    """Base for mesh-wide aggregate sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Tenda MW6",
            manufacturer="Tenda",
            model="Nova MW6",
        )

    @property
    def _eligible_clients(self) -> list[TendaMW6Client]:
        return [
            client
            for client in self.coordinator.data or []
            if client.raw_online not in (None, 0)
        ]

    @property
    def _inventory_fresh(self) -> bool:
        return bool(self._eligible_clients) and not self.coordinator.inventory_summary.all_reported_offline

    def _aggregate_rate_kib_s(self, direction: str) -> int | None:
        if not self._inventory_fresh:
            return None
        values = [
            client.raw_uprate if direction == "upload" else client.raw_downrate
            for client in self._eligible_clients
        ]
        valid_values = [value for value in values if value is not None and value >= 0]
        return sum(valid_values) if valid_values else None


class TendaMW6AggregateRateSensor(TendaMW6AggregateSensorBase):
    """Current sum of rates reported by all online MW6 clients."""

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        direction: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._direction = direction
        self._attr_icon = "mdi:upload-network" if direction == "upload" else "mdi:download-network"
        self._attr_native_unit_of_measurement = "KiB/s"
        self._attr_unique_id = f"{entry.entry_id}_aggregate_{direction}_rate"
        self._attr_name = f"Total {direction} rate"

    @property
    def available(self) -> bool:
        return super().available and self._aggregate_rate_kib_s(self._direction) is not None

    @property
    def native_value(self) -> int | None:
        return self._aggregate_rate_kib_s(self._direction)

    @property
    def extra_state_attributes(self) -> dict[str, int | bool | str]:
        return {
            "direction": self._direction,
            "online_clients": len(self._eligible_clients),
            "inventory_fresh": self._inventory_fresh,
            "source": "sum of MW6 HostList instantaneous KiB/s",
        }


class TendaMW6AggregateTransferSensor(TendaMW6AggregateSensorBase, RestoreEntity):
    """Locally accumulated transfer across all online MW6 clients."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        direction: str,
        period: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._direction = direction
        self._period = period
        self._total_bytes = 0.0
        self._period_key: str | None = None
        self._last_sample_at: datetime | None = None
        self._last_rate_kib_s: int | None = None
        self._has_valid_sample = False
        period_suffix = {"total": "", "day": " today", "month": " this month"}[period]
        self._attr_unique_id = f"{entry.entry_id}_aggregate_{direction}_transfer_{period}"
        self._attr_name = f"Total {direction} transfer{period_suffix}"

    async def async_added_to_hass(self) -> None:
        """Restore aggregate transfer state after a Home Assistant restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            restored_raw_bytes = last_state.attributes.get("total_bytes")
            if isinstance(restored_raw_bytes, (int, float)):
                self._total_bytes = max(0.0, float(restored_raw_bytes))
            else:
                try:
                    self._total_bytes = max(0.0, float(last_state.state)) * 1_000_000
                except (TypeError, ValueError):
                    pass
            restored_period_key = last_state.attributes.get("period_key")
            if isinstance(restored_period_key, str):
                self._period_key = restored_period_key
            restored_valid = last_state.attributes.get("has_valid_sample")
            self._has_valid_sample = (
                restored_valid if isinstance(restored_valid, bool) else self._total_bytes > 0
            )
        self._reset_period_if_needed(dt_util.now())

    def _current_period_key(self, now: datetime) -> str | None:
        if self._period == "day":
            return now.date().isoformat()
        if self._period == "month":
            return f"{now.year:04d}-{now.month:02d}"
        return None

    def _reset_period_if_needed(self, now: datetime) -> None:
        period_key = self._current_period_key(now)
        if period_key is None:
            return
        if self._period_key != period_key:
            self._total_bytes = 0.0
            self._period_key = period_key
            self._last_sample_at = None
            self._last_rate_kib_s = None
            self._has_valid_sample = False

    def _valid_rate_kib_s(self) -> int | None:
        return self._aggregate_rate_kib_s(self._direction)

    def _handle_coordinator_update(self) -> None:
        now = dt_util.utcnow()
        self._reset_period_if_needed(dt_util.now())
        rate = self._valid_rate_kib_s()
        if rate is None:
            self._last_sample_at = None
            self._last_rate_kib_s = None
        else:
            self._has_valid_sample = True
            if self._last_sample_at is not None and self._last_rate_kib_s is not None:
                elapsed = (now - self._last_sample_at).total_seconds()
                if 0 < elapsed <= 30:
                    self._total_bytes += estimate_transfer_bytes(self._last_rate_kib_s, elapsed)
            self._last_sample_at = now
            self._last_rate_kib_s = rate
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return super().available and self._has_valid_sample

    @property
    def native_value(self) -> float:
        return self._total_bytes / 1_000_000

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | int | None]:
        return {
            "direction": self._direction,
            "period": self._period,
            "period_key": self._period_key,
            "total_bytes": round(self._total_bytes),
            "online_clients": len(self._eligible_clients),
            "counting_active": self._valid_rate_kib_s() is not None,
            "has_valid_sample": self._has_valid_sample,
            "source": "locally integrated sum of online MW6 instantaneous KiB/s",
            "maximum_sample_gap_s": 30,
        }


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
        for client in self.coordinator.data or []:
            if client.mac.lower() == self._mac:
                return client
        return None

    @property
    def available(self) -> bool:
        return super().available and self._client is not None

    @property
    def client_identity_attributes(self) -> dict[str, str | bool | None]:
        """Stable metadata used by the bundled dashboard card."""
        client = self._client
        return {
            "tenda_mw6_client": True,
            "config_entry_id": self._entry.entry_id,
            "client_mac": client.mac.lower() if client is not None else self._mac,
            "client_ip": client.ip or None if client is not None else None,
            "client_name": (
                self.coordinator.client_display_name(client)
                if client is not None
                else self._mac
            ),
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
            **self.client_identity_attributes,
            "tenda_mw6_metric": "signal",
            "ip": client.ip,
            "mac": client.mac,
            "name": client.name,
            "node_sn": client.node_sn,
            "signal": client.signal,
            "access": client.access,
            "condition_time": client.condition_time,
        }

        # These values are kept as diagnostics only. The firmware schema names
        # them online/uprate/downrate, but live MW6 tests observed zero values
        # even for an active client. Do not expose them as authoritative HA state.
        summary = self.coordinator.inventory_summary
        if client.raw_online is None:
            inventory_state = "unknown"
        elif client.raw_online == 0:
            inventory_state = "reported_offline"
        else:
            inventory_state = "reported_online"

        attrs["raw_online"] = client.raw_online
        attrs["raw_uprate"] = client.raw_uprate
        attrs["raw_downrate"] = client.raw_downrate
        attrs["inventory_state"] = inventory_state
        attrs["inventory_all_reported_offline"] = summary.all_reported_offline
        attrs["rate_data_reliable"] = (
            client.raw_online not in (None, 0) and not summary.all_reported_offline
        )
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


class TendaMW6ClientAccessSensor(TendaMW6ClientSensorBase):
    """Connection type reported verbatim by the MW6 firmware."""

    _attr_icon = "mdi:lan-connect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator, entry, mac)
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_connection_type"
        self._attr_name = "Connection type"

    @property
    def native_value(self) -> str | None:
        client = self._client
        return client.access or None if client is not None else None


class TendaMW6ClientRateSensor(TendaMW6ClientSensorBase):
    """Fresh instantaneous rate reported by the MW6 HostList."""

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
        direction: str,
    ) -> None:
        super().__init__(coordinator, entry, mac)
        self._direction = direction
        self._attr_icon = "mdi:upload-network" if direction == "upload" else "mdi:download-network"
        self._attr_native_unit_of_measurement = "KiB/s"
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_{direction}_rate"
        self._attr_name = f"{direction.title()} rate"

    def _rate_kib_s(self) -> int | None:
        client = self._client
        if client is None or client.raw_online in (None, 0):
            return None
        if self.coordinator.inventory_summary.all_reported_offline:
            return None
        rate = client.raw_uprate if self._direction == "upload" else client.raw_downrate
        return rate if rate is not None and rate >= 0 else None

    @property
    def available(self) -> bool:
        return super().available and self._rate_kib_s() is not None

    @property
    def native_value(self) -> int | None:
        return self._rate_kib_s()

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        return {
            **self.client_identity_attributes,
            "tenda_mw6_metric": "rate",
            "direction": self._direction,
            "source": "MW6 HostList instantaneous KiB/s",
            "inventory_fresh": not self.coordinator.inventory_summary.all_reported_offline,
        }


class TendaMW6ClientTransferSensor(TendaMW6ClientSensorBase, RestoreEntity):
    """Locally accumulated transfer from valid MW6 instantaneous-rate samples."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: TendaMW6Coordinator,
        entry: ConfigEntry,
        mac: str,
        direction: str,
        period: str,
    ) -> None:
        super().__init__(coordinator, entry, mac)
        self._direction = direction
        self._period = period
        self._total_bytes = 0.0
        self._period_key: str | None = None
        self._last_sample_at: datetime | None = None
        self._last_rate_kib_s: int | None = None
        self._has_valid_sample = False
        period_suffix = {"total": "", "day": " today", "month": " this month"}[period]
        self._attr_unique_id = f"{entry.entry_id}_{self._mac}_{direction}_transfer_{period}"
        self._attr_name = f"{direction.title()} transfer{period_suffix}"

    async def async_added_to_hass(self) -> None:
        """Restore locally accumulated data after a Home Assistant restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            # Prefer the raw-byte attribute so changing the displayed unit does
            # not reinterpret a previously restored MB value as bytes.
            restored_raw_bytes = last_state.attributes.get("total_bytes")
            if isinstance(restored_raw_bytes, (int, float)):
                self._total_bytes = max(0.0, float(restored_raw_bytes))
            else:
                # Migration from <=1.0.0: the persisted state was native B.
                try:
                    self._total_bytes = max(0.0, float(last_state.state))
                except (TypeError, ValueError):
                    pass
            restored_period_key = last_state.attributes.get("period_key")
            if isinstance(restored_period_key, str):
                self._period_key = restored_period_key
            restored_valid = last_state.attributes.get("has_valid_sample")
            self._has_valid_sample = (
                restored_valid if isinstance(restored_valid, bool) else self._total_bytes > 0
            )
        self._reset_period_if_needed(dt_util.now())
        if self._valid_rate_kib_s() is not None:
            self._has_valid_sample = True

    def _current_period_key(self, now: datetime) -> str | None:
        if self._period == "day":
            return now.date().isoformat()
        if self._period == "month":
            return f"{now.year:04d}-{now.month:02d}"
        return None

    def _reset_period_if_needed(self, now: datetime) -> None:
        period_key = self._current_period_key(now)
        if period_key is None:
            return
        if self._period_key != period_key:
            self._total_bytes = 0.0
            self._period_key = period_key
            self._last_sample_at = None
            self._last_rate_kib_s = None
            self._has_valid_sample = False

    def _valid_rate_kib_s(self) -> int | None:
        client = self._client
        if client is None or client.raw_online in (None, 0):
            return None
        if self.coordinator.inventory_summary.all_reported_offline:
            return None
        rate = client.raw_uprate if self._direction == "upload" else client.raw_downrate
        return rate if rate is not None and rate >= 0 else None

    def _handle_coordinator_update(self) -> None:
        now = dt_util.utcnow()
        self._reset_period_if_needed(dt_util.now())
        rate = self._valid_rate_kib_s()
        if rate is None:
            self._last_sample_at = None
            self._last_rate_kib_s = None
        else:
            self._has_valid_sample = True
            if self._last_sample_at is not None and self._last_rate_kib_s is not None:
                elapsed = (now - self._last_sample_at).total_seconds()
                # Do not turn a delayed or missed poll into an invented transfer span.
                if 0 < elapsed <= 30:
                    self._total_bytes += estimate_transfer_bytes(self._last_rate_kib_s, elapsed)
            self._last_sample_at = now
            self._last_rate_kib_s = rate
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Avoid presenting an unvalidated 0 B baseline as real transfer."""
        return super().available and self._has_valid_sample

    @property
    def native_value(self) -> float:
        # Home Assistant displays decimal megabytes; accounting remains bytes.
        return self._total_bytes / 1_000_000

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | int | None]:
        return {
            **self.client_identity_attributes,
            "tenda_mw6_metric": "transfer",
            "direction": self._direction,
            "period": self._period,
            "period_key": self._period_key,
            "total_bytes": round(self._total_bytes),
            "counting_active": self._valid_rate_kib_s() is not None,
            "has_valid_sample": self._has_valid_sample,
            "source": "locally integrated MW6 instantaneous KiB/s",
            "maximum_sample_gap_s": 30,
        }


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
